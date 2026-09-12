# Privacy

MorrowFriends is an online multiplayer launcher. It has no advertising or
analytics SDK and does not create a MorrowFriends web account.

## Information used while playing

- The TES3MP game server receives normal network connection information and
  stores character/account data needed for multiplayer play.
- The voice service receives the connected account name, current cell, position,
  facing direction, and short-lived session tokens while proximity voice is
  active.
- Live voice is transported through the server's LiveKit service. Microphone
  access is optional and controlled by the voice and push-to-talk settings.

The voice relay keeps the latest live position state in memory. Voice claims
expire within ten minutes, player sessions expire within ten minutes, and a
game-server restart clears the relay's claims and sessions. Game-server logs
are rotated by size; the elapsed retention period therefore varies with
activity.

## Local information

The launcher stores its settings and managed TES3MP files beneath the current
Windows user's local application-data directory. It reads the local TES3MP log
to identify the account that logged in on that computer. It does not upload the
user's Morrowind game files.

Do not use a password from another service as a TES3MP character password.
