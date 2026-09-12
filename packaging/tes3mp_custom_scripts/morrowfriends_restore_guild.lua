-- Live repair: re-sync shared guild standing to everyone who is logged in.
--
-- Load as an admin (staffRank >= 2) with:
--   /load custom/morrowfriends_restore_guild
--
-- Why this is needed. config.shareFactionRanks is true, so guild rank lives in
-- world.json rather than in player records -- and base.lua pushes it to a client
-- only at LOGIN. When one player's progress writes a new rank into the shared
-- world mid-session, every other client keeps whatever it already had until it
-- next reconnects. The server believes the whole party is ranked while guild
-- NPCs go on offering those players the "how do I join" dialogue. This pushes
-- the world's ranks the same way a login does, without making anyone reconnect.
--
-- Expulsion is NOT shared (config.shareFactionExpulsion is false), so it is
-- handled per record. Flags are set to false rather than deleted:
-- StateHelper:LoadFactionExpulsion iterates the table and sends only the entries
-- it finds, so a deleted entry transmits nothing at all and the client goes on
-- believing it is expelled. Every faction the world knows about is given an
-- explicit false, which also makes a FUTURE un-expulsion transmissible for
-- players who currently have no entry to flip.
--
-- Idempotent: re-running it re-sends the same state.

local worldRanks = WorldInstance.data.factionRanks

if type(worldRanks) ~= "table" then
    worldRanks = {}
end

local restored = {}

for pid, player in pairs(Players) do
    if player ~= nil and player:IsLoggedIn() then

        local expulsion = player.data.factionExpulsion

        if type(expulsion) ~= "table" then
            expulsion = {}
            player.data.factionExpulsion = expulsion
        end

        local lifted = {}

        for factionId, state in pairs(expulsion) do
            if state ~= false then
                expulsion[factionId] = false
                table.insert(lifted, factionId)
            end
        end

        for factionId in pairs(worldRanks) do
            if expulsion[factionId] == nil then
                expulsion[factionId] = false
            end
        end

        -- Persist then push, matching the order the roster script's own
        -- permission changes use: write the record, then send the change so it
        -- applies without waiting for a reconnect.
        player:QuicksaveToDrive()

        WorldInstance:LoadFactionRanks(pid)
        WorldInstance:LoadFactionReputation(pid)
        player:LoadFactionExpulsion()

        restored[player.accountName] = lifted

        tes3mp.SendMessage(
            pid,
            "Your guild standing has been re-synced. Talk to guild members again.\n",
            false
        )
    end
end

return {
    worldRanks = worldRanks,
    restored = restored,
}
