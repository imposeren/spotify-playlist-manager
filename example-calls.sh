
# Just examples of how I used to run script
# Collect all the data to minimize requests to spotify API:
python3 ./spotify_playlist_manager.py collect

# Intersect some:
python3 ./spotify_playlist_manager.py --verbosity 3 --allow-replace --target-playlist "Karaoke (electro softer)" intersect "Electro (softer)" Karaoke

# Find tracks that I want to put into more playlists (e.g. by genres or by decade)
python3 ./spotify_playlist_manager.py --verbosity 1  --target-playlist "Need to clasify 2" playlist-counter --ignored-name-regex '2021-chill-investigate|For Share|src|src-soft|New Wave Party|Fantasy|Tabletop.*|Musica per Correre|Drama|romantic|Cheery, maybe joyful|Mystical|Ambient|Sport.*|Gaming|High|Residents The|Top Ten Heavy Metal 2022|Christmas|halloween|party .*|Super-Favs|.*araoke.*|Gaming - Racing|Mentor.FM Discovery|.*Shazam.*' --min-playlists 0 --max-playlists 1

# Find tracks that are not in "Hard" but also not in "non-hard" playlists:
python3 ./spotify_playlist_manager.py --verbosity 2 --allow-replace --target-playlist "Maybe soft-hard" not-in-playlists --source-playlist Karaoke "Harder (both electro and non-electro)" "non-hard (ex-calm,softer)"
