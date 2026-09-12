-- Live re-sync of every piece of state this server shares at login.
--
-- Load as an admin (staffRank >= 2) with:
--   /load custom/morrowfriends_resync_shared
--
-- Replaces morrowfriends_restore_guild, which covered only the faction half of
-- the same problem.
--
-- config.shareJournal, shareFactionRanks, shareFactionReputation and
-- shareTopics are all true, so that state lives in world.json rather than in
-- player records -- and base.lua pushes it to a client only at LOGIN. Progress
-- made mid-session reaches the shared world immediately but reaches the other
-- clients not at all, so the party silently drifts apart until each person
-- reconnects. It shows up as guild NPCs offering the "how do I join" dialogue
-- to a ranked member, or as quest and topic dialogue missing for someone who
-- was connected the whole time.
--
-- This pushes the world's copy to everyone connected, exactly the way a login
-- does, without making anyone reconnect.
--
-- Journal and topics are additive on the client, so this cannot take progress
-- away from anyone; it can only bring a stale client up to the world's state.
--
-- Expulsion is NOT shared (config.shareFactionExpulsion is false), so it is
-- handled per record. Flags are set to false rather than deleted:
-- StateHelper:LoadFactionExpulsion iterates the table and sends only the
-- entries it finds, so a deleted entry transmits nothing at all and the client
-- goes on believing it is expelled. Every faction the world knows about is
-- given an explicit false, which also makes a FUTURE un-expulsion
-- transmissible for a player who has no entry to flip yet.
--
-- Idempotent: re-running it re-sends the same state.

local worldRanks = WorldInstance.data.factionRanks

if type(worldRanks) ~= "table" then
    worldRanks = {}
end

local resynced = {}

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

        -- Same order base.lua uses when it loads a character.
        WorldInstance:LoadJournal(pid)
        WorldInstance:LoadFactionRanks(pid)
        player:LoadFactionExpulsion()
        WorldInstance:LoadFactionReputation(pid)
        WorldInstance:LoadTopics(pid)

        resynced[player.accountName] = lifted

        tes3mp.SendMessage(
            pid,
            "Quest log, dialogue topics and guild standing re-synced from the shared world.\n",
            false
        )
    end
end

return {
    journalEntries = #(WorldInstance.data.journal or {}),
    topics = #(WorldInstance.data.topics or {}),
    worldRanks = worldRanks,
    resynced = resynced,
}
