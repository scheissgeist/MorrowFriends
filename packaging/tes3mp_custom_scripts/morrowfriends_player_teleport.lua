-- MorrowFriends self-service teleportation.
-- Every player may move only their own character to another connected player.
-- No command argument is ever used as the origin player.

local TELEPORT_COOLDOWN_MS = time.seconds(2)
local lastTeleportAtMsByAccount = {}

local function connectedPlayerPid(target)
    local numericPid = tonumber(target)
    if numericPid ~= nil and Players[numericPid] ~= nil and Players[numericPid]:IsLoggedIn() then
        return numericPid
    end

    local wanted = string.lower(target)
    for otherPid, player in pairs(Players) do
        if player ~= nil and player:IsLoggedIn() then
            local accountName = tostring(player.accountName or "")
            local displayName = tostring(tes3mp.GetName(otherPid) or "")
            if string.lower(accountName) == wanted or string.lower(displayName) == wanted then
                return otherPid
            end
        end
    end
    return nil
end

local function onlinePlayerHint()
    local entries = {}
    for otherPid, player in pairs(Players) do
        if player ~= nil and player:IsLoggedIn() then
            table.insert(entries, tostring(otherPid) .. "=" .. tes3mp.GetName(otherPid))
        end
    end
    table.sort(entries)
    return table.concat(entries, ", ")
end

local function teleportSelfToPlayer(pid, cmd)
    if cmd[2] == nil then
        tes3mp.SendMessage(
            pid,
            "Use /goto <player name or id>. Online: " .. onlinePlayerHint() .. "\n",
            false
        )
        return
    end

    local target = tableHelper.concatenateFromIndex(cmd, 2)
    local targetPid = connectedPlayerPid(target)
    if targetPid == nil then
        tes3mp.SendMessage(
            pid,
            "That player is not connected. Online: " .. onlinePlayerHint() .. "\n",
            false
        )
        return
    end

    if targetPid == pid then
        tes3mp.SendMessage(pid, "You are already that player.\n", false)
        return
    end

    local accountName = tostring(Players[pid].accountName or pid)
    local now = tes3mp.GetMillisecondsSinceServerStart()
    local lastTeleportAtMs = lastTeleportAtMsByAccount[accountName]
    if lastTeleportAtMs ~= nil and now - lastTeleportAtMs < TELEPORT_COOLDOWN_MS then
        tes3mp.SendMessage(pid, "Wait two seconds before teleporting again.\n", false)
        return
    end
    lastTeleportAtMsByAccount[accountName] = now

    -- Both the requester and origin are always pid. The target supplied by the
    -- player is destination-only, so this cannot move another player.
    logicHandler.TeleportToPlayer(pid, pid, targetPid)
end

customCommandHooks.registerCommand("goto", teleportSelfToPlayer)
customCommandHooks.registerCommand("tpto", teleportSelfToPlayer)
customCommandHooks.registerCommand("teleportto", teleportSelfToPlayer)

jsonInterface.quicksave("player_teleport_status.json", {
    version = 1,
    enabledAtMs = tes3mp.GetMillisecondsSinceServerStart(),
})

for pid, player in pairs(Players) do
    if player ~= nil and player:IsLoggedIn() then
        tes3mp.SendMessage(
            pid,
            "Self teleport enabled: use /goto <player name or id>. You can move only yourself.\n",
            false
        )
    end
end

return {
    teleportSelfToPlayer = teleportSelfToPlayer,
}
