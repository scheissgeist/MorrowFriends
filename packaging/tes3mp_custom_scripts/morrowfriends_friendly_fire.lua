-- MorrowFriends: fighting each other is not a crime.
--
-- The problem
-- -----------
-- Bounties are decided entirely on the CLIENT. Morrowind's crime system watches
-- for a witnessed assault or murder and raises the local player's bounty, and
-- the client then reports the new figure to the server in a PlayerBounty packet.
-- The server never gets told WHY it went up, only that it did.
--
-- On a friends' server where brawling each other is half the point, that means
-- a scrap in a dungeon leaves everyone with a murder bounty and every town guard
-- in Vvardenfell hunting them.
--
-- The approach
-- ------------
-- Remember when a player last attacked another PLAYER, and refuse any bounty
-- increase that lands inside that window: push the previously saved figure back
-- to the client and block the default handler so the new one is never persisted.
--
-- This is deliberately a time window rather than an exact attribution, because
-- the bounty packet carries no cause. The trade-off is that a genuine crime
-- committed in the same few seconds as a player fight is also forgiven. That is
-- the right way round for this server: wrongly forgiving a theft costs nothing,
-- while wrongly keeping a murder bounty means guards attack on sight and the
-- only fix is a console command.
--
-- Crimes committed away from a player fight are untouched, and so are bounty
-- DECREASES, so serving time or paying a fine still works normally.
--
-- Verified against the TES3MP 0.8.1 CoreScripts:
-- - eventHandler.OnPlayerBounty runs customEventHooks.triggerValidators before
--   it saves anything, so a validator still sees the OLD persisted bounty in
--   Players[pid].data.fame.bounty while tes3mp.GetBounty(pid) already holds the
--   new client-side figure. That is what makes the revert possible without
--   having to track state from login.
-- - Returning makeEventStatus(false, true) from a validator skips only the
--   default handler; other scripts' handlers still run.
-- - OnObjectHit handlers receive (eventStatus, pid, cellDescription, objects,
--   targetPlayers), where targetPlayers is keyed by the victim's pid and each
--   entry carries hittingPid (nil when a creature or NPC landed the blow).

-- How long after swinging at another player a bounty still counts as "ours".
-- Morrowind raises the bounty on the killing blow itself, so this only has to
-- cover packet latency; it is kept short so unrelated crimes are not swept up.
local PVP_GRACE_MS = time.seconds(10)

-- pid -> server-uptime ms until which this player counts as brawling.
local pvpUntilMs = {}

local function nowMs()
    return tes3mp.GetMillisecondsSinceServerStart()
end

local function markPlayerCombat(pid)
    if pid == nil or Players[pid] == nil then
        return
    end
    pvpUntilMs[pid] = nowMs() + PVP_GRACE_MS
end

local function isBrawling(pid)
    local until_ = pvpUntilMs[pid]
    return until_ ~= nil and until_ > nowMs()
end

local function savedBountyFor(pid)
    local player = Players[pid]
    if player == nil or player.data == nil or player.data.fame == nil then
        return 0
    end
    local bounty = player.data.fame.bounty
    if type(bounty) ~= "number" then
        return 0
    end
    return bounty
end

-- Melee and ranged hits. The victim key tells us it was a player who got hit;
-- hittingPid tells us which player swung, which is who the crime attaches to.
-- Note this is NOT necessarily the packet sender: the cell authority forwards
-- hits on behalf of others.
customEventHooks.registerHandler("OnObjectHit", function(eventStatus, pid, cellDescription,
    objects, targetPlayers)
    if targetPlayers == nil then
        return eventStatus
    end
    for targetPid, targetPlayer in pairs(targetPlayers) do
        local hittingPid = targetPlayer.hittingPid
        -- hittingPid == targetPid is self-damage, which no one gets a bounty for.
        if hittingPid ~= nil and hittingPid ~= targetPid then
            markPlayerCombat(hittingPid)
        end
    end
    return eventStatus
end)

-- Death by any means, which is the case that actually matters: the murder
-- bounty lands here, and a kill by spell, summon or fall damage never produces
-- an ObjectHit from the killer at all.
customEventHooks.registerHandler("OnPlayerDeath", function(eventStatus, pid)
    if Players[pid] == nil then
        return eventStatus
    end
    if tes3mp.DoesPlayerHavePlayerKiller(pid) then
        local killerPid = tes3mp.GetPlayerKillerPid(pid)
        if killerPid ~= pid then
            markPlayerCombat(killerPid)
        end
    end
    return eventStatus
end)

customEventHooks.registerValidator("OnPlayerBounty", function(eventStatus, pid)
    local player = Players[pid]
    if player == nil or not player:IsLoggedIn() then
        return eventStatus
    end

    local incoming = tes3mp.GetBounty(pid)
    local saved = savedBountyFor(pid)

    -- Only increases are suppressed. A decrease is the player paying a fine or
    -- serving their sentence, and must always be allowed through.
    if incoming <= saved or not isBrawling(pid) then
        return eventStatus
    end

    tes3mp.SetBounty(pid, saved)
    tes3mp.SendBounty(pid)
    tes3mp.LogMessage(
        enumerations.log.INFO,
        "[MorrowFriends] Forgave a bounty of " .. tostring(incoming - saved) ..
            " for " .. logicHandler.GetChatName(pid) .. " (fighting another player)"
    )
    -- Skip the default handler so the rejected figure is never written to the
    -- player's record; custom handlers in other scripts still run.
    return customEventHooks.makeEventStatus(false, true)
end)

customEventHooks.registerHandler("OnPlayerDisconnect", function(eventStatus, pid)
    pvpUntilMs[pid] = nil
    return eventStatus
end)
