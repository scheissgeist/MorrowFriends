-- Live repair: lift every faction expulsion held by a logged-in player.
--
-- Load as an admin (staffRank >= 2) with:
--   /load custom/morrowfriends_clear_expulsion
--
-- Sets each expulsion flag to FALSE rather than deleting the entry.
-- StateHelper:LoadFactionExpulsion iterates pairs(factionExpulsion) and sends
-- only the entries it finds, so a deleted entry transmits nothing at all and the
-- client goes on believing it is expelled. The flag has to persist as an
-- explicit false for the un-expulsion to actually reach the player.
--
-- Online players only, deliberately. Their in-memory state is authoritative and
-- would overwrite any edit made to the saved JSON, so the fix has to go through
-- the live player object. Offline records are handled from the host side.
--
-- Idempotent: re-running it against already-cleared records changes nothing.

local cleared = {}

local function clearExpulsions(expulsion)
    if type(expulsion) ~= "table" then
        return nil
    end
    local lifted = {}
    for factionId, state in pairs(expulsion) do
        if state ~= false then
            expulsion[factionId] = false
            table.insert(lifted, factionId)
        end
    end
    return lifted
end

for pid, player in pairs(Players) do
    if player ~= nil and player:IsLoggedIn() then
        local lifted = clearExpulsions(player.data.factionExpulsion)

        if lifted ~= nil and #lifted > 0 then
            -- Quicksave then Load, matching the order the roster script's own
            -- permission changes use: persist the record, then push the change
            -- to the client so it applies without waiting for a reconnect.
            player:QuicksaveToDrive()
            player:LoadFactionExpulsion()

            cleared[player.accountName] = lifted

            tes3mp.SendMessage(
                pid,
                "Your guild expulsions have been lifted (" ..
                    table.concat(lifted, ", ") .. ").\n",
                false
            )
        end
    end
end

return {
    cleared = cleared,
}
