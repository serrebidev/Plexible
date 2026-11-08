## Fixes
- Screen reader announcements now actually speak: status messages and player feedback go through the NVDA controller client (status messages never interrupt; answers to keys you pressed do). Silent no-op when NVDA is not running
- Stop music without freezing: stopping a track no longer waits for a resume point Plex never stores for tracks, and listing radio options no longer floods the server with seed queries (the seed is picked only when a radio is started)
- Open music letters quickly: browsing artists, albums and tracks by letter now shows the right items with correct titles and counts, loaded in one paged request per letter instead of reloading every item
