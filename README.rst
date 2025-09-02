======
README
======

Script to do some operations on spotify playlists.


Usage
=====

This is not a user-fiendly "package", it's just a python3 "script" for your own use, so many things must be done manually:

* Create virtualenv if you need it

* Install requirements with ``pip3 install -r requirements.txt``

Some environment variables are needed to run it. Example environment commands::

   export SPOTIPY_CLIENT_ID=PUT_YOUR_SPOTIFY_API_CLIENT_ID_HERE
   export SPOTIPY_CLIENT_SECRET=PUT_YOUR_SPOTIFY_API_CLIENT_SECRET_HERE
   export SPOTIPY_OPEN_BROWSER=False

For details on environment variables see `spotipy documentation <https://spotipy.readthedocs.io/en/2.25.1/index.html#getting-started>`__

See usage infor with ``--help``: ``python3 spotify_playlist_manager.py --help``

Some example calls can be seen in ``example-calls.sh`` file.
