-- One-time live repair for the 2026-08-14 Balmora Mages Guild incident.
-- Load as the server owner with:
--   /load custom/morrowfriends_restore_mages
--
-- The three actor records were already revived in their cell save. This module
-- clears only their shared-world death counters so GetDeadCount-based quests do
-- not continue treating them as dead. It is intentionally idempotent.

local restoredRefIds = {
    "ajira",
    "estirdalin",
    "masalinie merian",
}

for _, refId in ipairs(restoredRefIds) do
    WorldInstance.data.kills[refId] = 0
end

WorldInstance:QuicksaveToDrive()

for pid, player in pairs(Players) do
    if player ~= nil and player:IsLoggedIn() then
        tes3mp.SendMessage(
            pid,
            "Balmora Mages Guild death counters restored: Ajira, Estirdalin, and Masalinie Merian.\n",
            false
        )
    end
end

return {
    restoredRefIds = restoredRefIds,
}
