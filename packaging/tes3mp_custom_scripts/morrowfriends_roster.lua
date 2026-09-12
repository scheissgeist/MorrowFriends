-- MorrowFriends: writes the live connected-player roster to server/data/live_players.json
-- and polls server/data/host_commands.json for host-issued actions (kick, teleport,
-- broadcast) so the launcher GUI can drive the server without an in-game character.
--
-- Verified against the actual TES3MP 0.8.1 CoreScripts:
-- - OnPlayerConnect/OnPlayerDisconnect fire customEventHooks.triggerHandlers(...) in
--   eventHandler.lua after the real Players[pid] table is updated.
-- - jsonInterface.load(fileName) / jsonInterface.save(fileName, data) (server/lib/lua/
--   jsonInterface.lua) is CoreScripts' own file I/O — paths are relative to
--   config.dataPath automatically, same pattern used by world/json.lua and
--   player/json.lua. NOT a raw io.open with a hand-built path.
-- - tes3mp.CreateTimer(globalFnName, time.seconds(n)) / StartTimer / RestartTimer is
--   the real repeating-timer API (serverCore.lua's own UpdateTime uses it); the
--   callback must be a bare global function.
-- - tes3mp.SendMessage(pid, message, sendToOthers) requires a real connected pid as
--   the anchor even for a broadcast — there is no pid-0 "everyone" sentinel.

local ROSTER_FILE = "live_players.json"
local COMMAND_FILE = "host_commands.json"
-- Read on the 200ms position tick, not the 1s command tick, so the in-game
-- push-to-talk indicator does not lag behind the key by up to a second.
local PTT_FILE = "ptt_state.json"
-- Account that gets owner rank + console automatically on login.
local OWNER_NAME = "Gorid"
local RESULT_FILE = "host_command_result.json"
local VOICE_CLAIMS_FILE = "voice_claims.json"
local POSITION_SAMPLE_MS = 200
-- Claims are one-time-use, so a player who redeems one has none left. Minting a
-- replacement on a short cycle keeps an unused claim available the whole time
-- someone is logged in, instead of only for five minutes after login — which
-- stranded anyone who opened voice later in the session (2026-08-21).
-- LIFETIME must stay at or under the relay's 10-minute MAX_CLAIM_LIFETIME_MS or
-- the relay rejects the entire claims message as malformed.
local VOICE_CLAIM_LIFETIME_MS = time.minutes(5)
local VOICE_CLAIM_REFRESH_MS = time.minutes(1)
local rosterSequence = 0
local voiceClaims = {}
local issuedVoiceFor = {}

-- TES3MP gives every player TWO names and they are not interchangeable:
--   player.accountName  - the login name. The saved record on disk is keyed by
--                         it, findPidByName matches on it, and the relay issues
--                         voice claims against it.
--   tes3mp.GetName(pid) - the in-game character name, chosen by the player at
--                         character creation. It can be anything at all.
--
-- Publishing the character name is what broke voice on 2026-08-22: an account
-- named "Guard" was playing a character named "rottencheeseCA", so the roster
-- listed rottencheeseCA twice and Guard not at all. Guard's login consumed the
-- claim minted under "rottencheeseCA", and the real rottencheeseCA was left
-- with none — his auto-claim just returned 400 forever.
--
-- Identity is ALWAYS the account name. GetName is a display string.
local function accountNameFor(pid)
    local player = Players[pid]
    if player ~= nil and player.accountName ~= nil and player.accountName ~= "" then
        return player.accountName
    end
    -- Only reachable before login finalises, when accountName is not populated
    -- yet. Callers all gate on IsLoggedIn(), so this is a belt-and-braces path.
    return tes3mp.GetName(pid)
end

local function writeVoiceClaims()
    jsonInterface.quicksave(VOICE_CLAIMS_FILE, {
        version = 1,
        serverUptimeMs = tes3mp.GetMillisecondsSinceServerStart(),
        claims = voiceClaims,
    })
end

local function cleanVoiceClaims()
    local now = tes3mp.GetMillisecondsSinceServerStart()
    for code, claim in pairs(voiceClaims) do
        if claim.expiresAtMs == nil or claim.expiresAtMs <= now then
            voiceClaims[code] = nil
        end
    end
end

local function voiceClaimIsFresh(playerName)
    local now = tes3mp.GetMillisecondsSinceServerStart()
    for _, claim in pairs(voiceClaims) do
        if claim.player == playerName
            and claim.expiresAtMs > now
            and (now - claim.issuedAtMs) < VOICE_CLAIM_REFRESH_MS then
            return true
        end
    end
    return false
end

local function issueVoiceClaim(pid, announce)
    cleanVoiceClaims()
    local playerName = accountNameFor(pid)
    for code, claim in pairs(voiceClaims) do
        if claim.player == playerName then
            voiceClaims[code] = nil
        end
    end
    local code = tes3mp.GenerateRandomString(16):upper()
    local issuedAt = tes3mp.GetMillisecondsSinceServerStart()
    voiceClaims[code] = {
        player = playerName,
        issuedAtMs = issuedAt,
        expiresAtMs = issuedAt + VOICE_CLAIM_LIFETIME_MS,
    }
    writeVoiceClaims()
    -- Only /voice announces the code. Nothing prints it unprompted: the page
    -- redeems a claim by NAME within seconds, and Morrowind's chat is not
    -- selectable text, so a 16-character code shown here cannot be copied and
    -- usually cannot be retyped accurately either.
    if announce then
        tes3mp.SendMessage(
            pid,
            "Voice setup code: " .. code .. "\nEnter this on the voice page if it did not attach on its own.\n",
            false
        )
    end
end

customCommandHooks.registerCommand("voice", function(pid, cmd)
    issueVoiceClaim(pid, true)
end)

-- /goto <name> — travel to another player. Available to EVERYONE, no rank.
--
-- Deliberately one-directional: the caller is ALWAYS the one who moves.
-- TeleportToPlayer(pid, originPid, targetPid) moves originPid to targetPid, so
-- passing the caller as origin means a player can go to someone, but can never
-- yank another player to themselves or shove one player at another. Without
-- that constraint any player could drag anyone anywhere, which is a griefing
-- tool on an open server.
customCommandHooks.registerCommand("goto", function(pid, cmd)
    if Players[pid] == nil or not Players[pid]:IsLoggedIn() then
        return
    end
    local wanted = tableHelper.concatenateFromIndex(cmd, 2)
    if wanted == nil or wanted == "" then
        tes3mp.SendMessage(pid, color.Warning .. "Use /goto <player name>\n", false)
        return
    end

    local targetPid = nil
    local wantedLower = string.lower(wanted)
    for otherPid, player in pairs(Players) do
        if player ~= nil and player:IsLoggedIn() then
            -- Match EITHER name. The name floating over someone's head in game
            -- is the character name, but the roster and the panel show the
            -- account name, so a player can reasonably type either one.
            local account = accountNameFor(otherPid)
            local liveName = tes3mp.GetName(otherPid)
            if (account ~= nil and string.lower(account) == wantedLower)
                or (liveName ~= nil and string.lower(liveName) == wantedLower) then
                targetPid = otherPid
                break
            end
        end
    end

    if targetPid == nil then
        tes3mp.SendMessage(pid, color.Warning .. wanted .. " is not online.\n", false)
        return
    end
    if targetPid == pid then
        tes3mp.SendMessage(pid, color.Warning .. "You are already there.\n", false)
        return
    end

    -- caller is origin: the CALLER moves, nobody else is touched.
    logicHandler.TeleportToPlayer(pid, pid, targetPid)
end)

local function writeRoster()
    local entries = {}
    for pid, player in pairs(Players) do
        if player ~= nil and player:IsLoggedIn() then
            local playerName = accountNameFor(pid)
            table.insert(entries, {
                pid = pid,
                name = playerName,
                cell = tes3mp.GetCell(pid),
                exterior = tes3mp.IsInExterior(pid),
                position = {
                    x = tes3mp.GetPosX(pid),
                    y = tes3mp.GetPosY(pid),
                    z = tes3mp.GetPosZ(pid),
                },
                rotation = {
                    x = tes3mp.GetRotX(pid),
                    z = tes3mp.GetRotZ(pid),
                },
            })
            -- Login is not a single hook in 0.8.1. Issue one claim the first
            -- time this account appears as logged in during the session, then
            -- keep a spare minted so voice can be attached at any point later.
            if playerName ~= nil and playerName ~= "" then
                if issuedVoiceFor[playerName] ~= true then
                    -- Mint the claim, but do NOT print the code. Voice attaches
                    -- on its own. Recovery is the launcher's Voice button, not
                    -- a chat code nobody can copy off a fullscreen game.
                    issueVoiceClaim(pid, false)
                    issuedVoiceFor[playerName] = true
                    tes3mp.SendMessage(
                        pid,
                        "Voice attaches automatically. If it does not, open Voice in MorrowFriends.\n",
                        false
                    )
                    -- Grant the owner their admin rank on login rather than
                    -- hand-editing a JSON file that does not exist until they
                    -- have played once. Applied every session so it survives a
                    -- wiped or recreated character.
                    -- Deliberately NOT accountNameFor(): owner rank grants staff
                    -- rank 3 and the console, so it must match the login account
                    -- and nothing else. accountNameFor falls back to the
                    -- character name, which any player picks for themselves —
                    -- matching on that would hand the console to anyone who
                    -- named their character "Gorid".
                    local ownerAccount = Players[pid].accountName
                    if ownerAccount ~= nil
                        and string.lower(ownerAccount) == string.lower(OWNER_NAME) then
                        Players[pid].data.settings.staffRank = 3
                        Players[pid].data.settings.consoleAllowed = true
                        Players[pid]:QuicksaveToDrive()
                        Players[pid]:LoadSettings()
                        tes3mp.SendMessage(
                            pid,
                            color.LimeGreen .. "Owner rank active. Console enabled (~).\n"
                                .. color.Default,
                            false
                        )
                    end
                elseif not voiceClaimIsFresh(playerName) then
                    -- Silent. The launcher redeems these automatically, so
                    -- announcing a renewal every minute would flood chat.
                    issueVoiceClaim(pid, false)
                end
            end
        end
    end
    rosterSequence = rosterSequence + 1
    jsonInterface.quicksave(ROSTER_FILE, {
        version = 1,
        sequence = rosterSequence,
        serverUptimeMs = tes3mp.GetMillisecondsSinceServerStart(),
        players = entries,
    })
end

-- Account names ONLY, case-insensitively.
--
-- This resolves the target of every host command, including grant_host_owner,
-- so it must never match the character name: that is player-chosen, so honouring
-- it would let anyone claim a command aimed at someone else simply by naming
-- their character after them. Case is folded because these names are typed by
-- hand into the panel and by the PTT feed.
local function findPidByName(name)
    if name == nil then
        return nil
    end
    local lowered = string.lower(tostring(name))
    for pid, player in pairs(Players) do
        if player ~= nil and player:IsLoggedIn()
            and player.accountName ~= nil
            and string.lower(player.accountName) == lowered then
            return pid
        end
    end
    return nil
end

-- Case-insensitive identity check against BOTH names a player answers to.
-- live_players.json now publishes the account name, but host commands are typed
-- by hand and arrive in whatever case the sender used ("artyom" typed, and
-- "Artyom.json" on disk), and a player may also be referred to by the character
-- name shown above their head. Matching one form exactly would silently skip the
-- player instead of reporting a miss.
local function playerAnswersTo(pid, player, wanted)
    if wanted == nil then
        return true
    end
    local lowered = string.lower(tostring(wanted))
    if player.accountName ~= nil and string.lower(player.accountName) == lowered then
        return true
    end
    local liveName = tes3mp.GetName(pid)
    return liveName ~= nil and string.lower(liveName) == lowered
end

local function anyConnectedPid()
    for pid, player in pairs(Players) do
        if player ~= nil and player:IsLoggedIn() then
            return pid
        end
    end
    return nil
end

local function saveAllServerState()
    local playerCount = 0
    for pid, player in pairs(Players) do
        if player ~= nil and player:IsLoggedIn() then
            -- These are the same packet snapshots CoreScripts takes during a
            -- normal disconnect. They capture the exact cell/coordinates and
            -- current health/magicka/fatigue before the player's JSON is saved.
            player:SaveCell(packetReader.GetPlayerPacketTables(pid, "PlayerCellChange"))
            player:SaveStatsDynamic(packetReader.GetPlayerPacketTables(pid, "PlayerStatsDynamic"))
            player:SaveToDrive()
            playerCount = playerCount + 1
        end
    end
    WorldInstance:SaveToDrive()
    for _, recordStore in pairs(RecordStores) do
        recordStore:SaveToDrive()
    end
    return playerCount
end

local function runHostCommand(cmd)
    if cmd.action == "save_all" then
        return saveAllServerState()
    elseif cmd.action == "kick" then
        local pid = findPidByName(cmd.target)
        -- Players[pid]:Kick() (player/base.lua) does self:Destroy() before
        -- tes3mp.Kick(pid) — calling tes3mp.Kick directly skips that server-side
        -- state cleanup, which is what commandHandler.lua's own /kick uses.
        if pid ~= nil and Players[pid] ~= nil then
            Players[pid]:Kick()
        end
    elseif cmd.action == "ban" then
        local pid = findPidByName(cmd.target)
        if pid ~= nil and Players[pid] ~= nil then
            -- CoreScripts persists the account-name ban and bans every IP
            -- already stored for the account. Kick through the Player object
            -- afterwards so the normal server-side cleanup still runs.
            logicHandler.BanPlayer(pid, Players[pid].accountName)
            Players[pid]:Kick()
        end
    elseif cmd.action == "teleport_to_host" then
        local targetPid = findPidByName(cmd.target)
        local hostPid = findPidByName(cmd.host)
        if targetPid ~= nil and hostPid ~= nil then
            logicHandler.TeleportToPlayer(targetPid, targetPid, hostPid)
        end
    elseif cmd.action == "teleport_host_to" then
        local targetPid = findPidByName(cmd.target)
        local hostPid = findPidByName(cmd.host)
        if targetPid ~= nil and hostPid ~= nil then
            logicHandler.TeleportToPlayer(hostPid, hostPid, targetPid)
        end
    elseif cmd.action == "broadcast" then
        local anchorPid = anyConnectedPid()
        if anchorPid ~= nil then
            tes3mp.SendMessage(anchorPid, "[Host] " .. tostring(cmd.message) .. "\n", true)
        end
    elseif cmd.action == "give_gold" then
        -- Gold_001 verified directly against Morrowind.esm's MISC records (not
        -- memory-recalled). Pattern (mutate inventory table, then Quicksave +
        -- LoadInventory to push to client) matches menuHelper.ProcessEffects,
        -- CoreScripts' own "give item" effect handler.
        local pid = findPidByName(cmd.target)
        local amount = tonumber(cmd.amount)
        if pid ~= nil and Players[pid] ~= nil and amount ~= nil and amount > 0 then
            inventoryHelper.addItem(Players[pid].data.inventory, "Gold_001", math.floor(amount), -1, -1)
            Players[pid]:QuicksaveToDrive()
            Players[pid]:LoadInventory()
            -- Reload the saved equipment immediately after the full inventory
            -- refresh. CoreScripts' own item-effect path does both; omitting
            -- this call leaves the client with every equipment slot cleared.
            Players[pid]:LoadEquipment()
        end
    elseif cmd.action == "grant_host_owner" then
        local pid = findPidByName(cmd.target)
        if pid ~= nil and Players[pid] ~= nil then
            -- The launcher host is the server owner. Owner rank unlocks the
            -- TES3MP admin chat commands; consoleAllowed unlocks the tilde
            -- console. LoadSettings pushes the permission change immediately.
            Players[pid].data.settings.staffRank = 3
            Players[pid].data.settings.consoleAllowed = true
            Players[pid]:QuicksaveToDrive()
            Players[pid]:LoadSettings()
            tes3mp.SendMessage(
                pid,
                "Host console enabled. Press ~ for the console; use /help for server commands.\n",
                false
            )
            return true
        end
        return false
    elseif cmd.action == "revoke_host_owner" then
        local pid = findPidByName(cmd.target)
        if pid ~= nil and Players[pid] ~= nil then
            -- Mirror of grant_host_owner. Drops the player back to a normal
            -- account: no admin chat commands, no tilde console. LoadSettings
            -- applies it live so the change does not wait for a reconnect.
            Players[pid].data.settings.staffRank = 0
            Players[pid].data.settings.consoleAllowed = false
            Players[pid]:QuicksaveToDrive()
            Players[pid]:LoadSettings()
            return true
        end
        -- OFFLINE PATH. findPidByName only matches logged-in players, so the
        -- first version of this silently did nothing whenever the target had
        -- disconnected — which is exactly when you most want to revoke someone
        -- (2026-08-18: Vicksauce kept Owner rank because every revoke landed
        -- while he was offline). Edit the saved record directly instead.
        local path = "player/" .. cmd.target .. ".json"
        local record = jsonInterface.load(path)
        if record ~= nil and type(record) == "table" then
            if type(record.settings) ~= "table" then
                record.settings = {}
            end
            record.settings.staffRank = 0
            record.settings.consoleAllowed = false
            jsonInterface.quicksave(path, record)
            return true
        end
        return false
    elseif cmd.action == "clear_expulsion" then
        -- Lifts guild expulsions for LOGGED-IN players only. A connected
        -- player's faction state lives in memory and overwrites the saved JSON
        -- on the next save, so an edit to the file would be silently discarded;
        -- offline records are cleared by the panel directly instead.
        --
        -- Each flag is set to FALSE rather than removed. StateHelper's
        -- LoadFactionExpulsion iterates pairs(factionExpulsion) and sends only
        -- the entries it finds, so a deleted entry transmits nothing at all and
        -- the client goes on believing it is expelled.
        --
        -- cmd.target nil means every connected player.
        local cleared = 0

        for pid, player in pairs(Players) do
            if player ~= nil and player:IsLoggedIn()
                and playerAnswersTo(pid, player, cmd.target) then

                local expulsion = player.data.factionExpulsion
                local lifted = false

                if type(expulsion) == "table" then
                    for factionId, state in pairs(expulsion) do
                        if state ~= false then
                            expulsion[factionId] = false
                            lifted = true
                        end
                    end
                end

                if lifted then
                    -- Quicksave then Load, the same order the permission
                    -- changes above use: persist the record, then push it to
                    -- the client so it applies without a reconnect.
                    player:QuicksaveToDrive()
                    player:LoadFactionExpulsion()
                    cleared = cleared + 1
                    tes3mp.SendMessage(
                        pid, "Your guild expulsions have been lifted.\n", false
                    )
                end
            end
        end

        return cleared
    end
end

function MorrowFriendsPollCommands()
    local cmd = jsonInterface.load(COMMAND_FILE)
    if cmd ~= nil and type(cmd) == "table" and cmd.action ~= nil then
        jsonInterface.quicksave(COMMAND_FILE, {})
        local ok, detail = pcall(runHostCommand, cmd)
        local result = {
            requestId = cmd.requestId,
            action = cmd.action,
            ok = ok,
        }
        if ok then
            result.detail = detail
        else
            result.error = tostring(detail)
        end
        jsonInterface.quicksave(RESULT_FILE, result)
    end
    tes3mp.RestartTimer(morrowFriendsCommandTimerId, time.seconds(1))
end

-- In-game push-to-talk indicator.
--
-- TES3MP 0.8.1 exposes NO persistent HUD to server Lua — the only GUI calls are
-- MessageBox / CustomMessageBox / ListBox / SendMessage, all modal except chat
-- (verified against docs.tes3mp.com GUI Functions, 2026-08-18). SendMessage
-- writes a chat line, and with the client's chat in CHAT_HIDDENMODE that line
-- appears and then fades after `delay` seconds (GUIChat::update in Source.zip).
-- That is the only zero-recompile way to put voice state on the game screen.
--
-- Only fires on a CHANGE, never per tick, or it would flood the chat log.
local lastPttTalking = nil

local function pushPttIndicator()
    local state = jsonInterface.load(PTT_FILE)
    if state == nil or type(state) ~= "table" or state.version ~= 1 then
        return
    end
    local talking = state.talking == true
    if talking == lastPttTalking then
        return
    end
    lastPttTalking = talking

    local name = tostring(state.player or "")
    if name == "" then
        return
    end
    local pid = findPidByName(name)
    if pid == nil or Players[pid] == nil then
        return
    end
    if talking then
        tes3mp.SendMessage(pid, color.LimeGreen .. "[ MIC ON ]" .. color.Default .. "\n", false)
    else
        tes3mp.SendMessage(pid, color.Grey .. "[ mic off ]" .. color.Default .. "\n", false)
    end
end

function MorrowFriendsWritePositionSnapshot()
    -- A real client connect fires OnPlayerConnect before IsLoggedIn becomes
    -- true, and there is no hook at the exact login-finalize transition. This
    -- fixed-rate snapshot therefore serves both roster discovery and the
    -- authoritative position feed used by proximity voice.
    writeRoster()
    pushPttIndicator()
    tes3mp.RestartTimer(morrowFriendsPositionTimerId, POSITION_SAMPLE_MS)
end

customEventHooks.registerHandler("OnPlayerConnect", function(eventStatus, pid)
    writeRoster()
    return eventStatus
end)

customEventHooks.registerHandler("OnPlayerDisconnect", function(eventStatus, pid)
    local playerName = accountNameFor(pid)
    if playerName ~= nil then
        issuedVoiceFor[playerName] = nil
    end
    writeRoster()
    return eventStatus
end)

customEventHooks.registerHandler("OnServerPostInit", function(eventStatus)
    writeRoster()
    voiceClaims = {}
    issuedVoiceFor = {}
    writeVoiceClaims()
    jsonInterface.quicksave(COMMAND_FILE, {})
    jsonInterface.quicksave(RESULT_FILE, {})
    morrowFriendsCommandTimerId = tes3mp.CreateTimer("MorrowFriendsPollCommands", time.seconds(1))
    morrowFriendsPositionTimerId = tes3mp.CreateTimer(
        "MorrowFriendsWritePositionSnapshot", POSITION_SAMPLE_MS
    )
    tes3mp.StartTimer(morrowFriendsCommandTimerId)
    tes3mp.StartTimer(morrowFriendsPositionTimerId)
    return eventStatus
end)

customEventHooks.registerHandler("OnServerExit", function(eventStatus, ...)
    -- Write a VALID empty snapshot, not a bare {}. The launcher's relay bridge
    -- rejects any payload whose version ~= 1 and then stops publishing
    -- entirely, so a bare {} leaves the relay with no feed at all rather than
    -- with an honest "nobody is connected" (2026-08-18).
    rosterSequence = rosterSequence + 1
    jsonInterface.quicksave(ROSTER_FILE, {
        version = 1,
        sequence = rosterSequence,
        serverUptimeMs = tes3mp.GetMillisecondsSinceServerStart(),
        players = {},
    })
    voiceClaims = {}
    writeVoiceClaims()
    return eventStatus
end)
