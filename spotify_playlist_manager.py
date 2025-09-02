#!/usr/bin/env python3
# Shows the top tracks for a user

import argparse
import datetime
import os
import pickle
import pprint
import re

import spotipy
from spotipy.oauth2 import SpotifyOAuth


parser = argparse.ArgumentParser(
    prog='spotify_playlist_manager.py',
    description='Spotify Playlist Manager',
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
)

parser.add_argument(
    '-v', '--verbosity',
    type=int, choices=[0, 1, 2, 3],
    default=1,
)

parser.add_argument('--dry-run', action='store_true')

parser.add_argument(
    '--target-playlist', required=True,
    help='Name or id of the playlist where tracks will be saved.'
)
target_exists_group = parser.add_mutually_exclusive_group()
target_exists_group.add_argument(
    '--allow-replace', action='store_true',
    help=(
        'If target playlist already exists, then this option allows to replace tracks in it instead of raising '
        'error.'
    ),
)
target_exists_group.add_argument(
    '--allow-append', action='store_true',
    help=(
        'If target playlist already exists, then this option allows to appendtracks toit instead of raising '
        'error.'
    ),
)

subparsers = parser.add_subparsers(help='subcommand help', dest='command')

subparsers.add_parser('show-playlists', help='Show raw data for all user playlists')

subparsers.add_parser(
    'collect',
    help=(
        'Collect or update local tracks and playlists data. If data is once collected, then all other commands '
        'will use locally collected data: to use newer data in such a case: either delete collected pickle file, '
        'or run `collect` command again.'
    ),
)

intersect_parser = subparsers.add_parser(
    'intersect',
    help='Intersect 2+ playlists, e.g. `intersect Instrumental "Electro (softer)"`',
)
intersect_parser.add_argument(
    'names_or_ids', nargs='+',
    help=(
        'Names or ids of playlists to intersect. '
        'At least 2 different playlits are required and if name is used then it must be unique'
    ),
)

_runs_collect_warning = (
    'WARNING! If data is not yet collected then also runs `collect` command (see respective help section for details)'
)

playlist_counter_parser = subparsers.add_parser(
    'playlist-counter',
    help=(
        'Create a new playlist with saved/liked tracks that have specific number of user playlists using them, e.g. '
        f'with tracks that are only in 0-2 playlists. {_runs_collect_warning}.'
    ),
)

playlist_counter_parser.add_argument(
    '--min-playlists', default=0, type=int,
    help='Minimum numer of playlists the track must be in',
)

playlist_counter_parser.add_argument(
    '--max-playlists', type=int,
    help='Maximum number of playlists the track must be in (defaults to the value of --min-playlists)',
)

playlist_counter_parser.add_argument(
    '--ignored-description-regex',
    default='Generated with .*',
    help='Playlists with description matching this regex pattern will be ignored when counting track\'s playlists',
)

playlist_counter_parser.add_argument(
    '--ignored-name-regex',
    default='(Mentor.FM Discovery|.*Shazam.*)',
    help='Playlists with name matching this regex pattern will be ignored when counting track\'s playlists',
)

not_in_playlists_parser = subparsers.add_parser(
    'not-in-playlists',
    help=(
        'Create a playlist with saved/liked tracks that are not in some playlists. '
        'Example usage: you have "Electro" playlist and "non-electro" playlist and want to find all tracks that are '
        f'not yet in these 2 playlists. {_runs_collect_warning}.'
    ),
)

not_in_playlists_parser.add_argument(
    'checked_playlists',
    nargs='*',
    help=(
        'Names or IDs of playlists where tracks should not be present. '
        'Required if `--target-playlists-name-regex` is not used'
    ),
)

not_in_playlists_parser.add_argument(
    '--checked-playlists-name-regex',
    help=(
        'Playlists with name mathcing this pattern are the ones where tracks should not be present. '
        'Required if `target_playlists` arguments are not used.'
    ),
)

not_in_playlists_parser.add_argument(
    '--source-playlist',
    help=(
        'Name or id of the playlist where tracks will be checked (instead of going over all liked tracks).'
    ),
)

class SpotifyManagerError(Exception):
    pass


class SpotifyMisconfigured(SpotifyManagerError):
    pass


class SpotifyCommandError(SpotifyManagerError):
    pass


def _chunked(iterable, page_size=100):
    for i in range(0, len(iterable), page_size):
        yield iterable[i:i+page_size]


class SpotifyManager(object):
    _client = None
    verbosity = 1

    def __init__(self):
        self.init_config()
        self.init_collection()
        self.init_data()
        self.current_user = None

    def init_data(self):
        self.__data = {
            'playlists_by_id': {},
            'playlists_by_name': {},
            'playlist_tracks': {},
            'tracks': {},
            'tracks_in_playlists': {},
            'current_user_saved_tracks': [],
        }

    def init_collection(self):
        workdir = os.getcwd()
        self.__collection = {
            '_save': False,
            '_date_collected': None,
        }
        self._collection_file_path = os.path.join(workdir, 'spotify_collection.pickle')
        if os.path.exists(self._collection_file_path):
            with open(self._collection_file_path, 'rb') as f:
                try:
                    self.__collection = pickle.load(f)
                except Exception:
                    raise RuntimeError(
                        f"File {self._collection_file_path,!r} with collected data is corrupt. Please remove it."
                    )
                else:
                    self.__collection['_save'] = False
                    self.print(f"Collected data found in {self._collection_file_path} so no API calls will be made")
                    self.print(f"Data was collected on {self.collection['_date_collected']}")

    def init_config(self):
        self.config = {}
        prefix = 'SPOTIPY_'
        key_handlers_defaults = {
            'CLIENT_ID': (None, None),
            'CLIENT_SECRET': (None, None),
            'REDIRECT_URI': (None, 'https://127.0.0.1:8000/'),
            'SCOPES': (
                lambda v: v.split(':'),
                [
					'user-library-read',
					'user-library-modify',
					'playlist-modify-private',
					'playlist-modify-public',
					'user-top-read',
                ],
            ),
            'OPEN_BROWSER': (
                lambda v: bool(v.lower() in '1yt'),
                True,
            ),
        }

        for key, (handler, default) in key_handlers_defaults.items():
            val = os.environ.get(prefix + key, None)
            if val is not None:
                if handler:
                    val = handler(val)
            elif default is not None:
                val = default
            self.config[key] = val
        if not (self.config['CLIENT_ID'] and self.config['CLIENT_SECRET']):
            raise SpotifyMisconfigured(
                'SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET must be '
                'configured in environ'
            )

    @property
    def data(self):
        return self.__data

    @property
    def collection(self):
        return self.__collection

    @property
    def client(self):
        if not self._client:
            self._client = spotipy.Spotify(
                auth_manager=SpotifyOAuth(
                    self.config['CLIENT_ID'],
                    self.config['CLIENT_SECRET'],
                    redirect_uri=self.config['REDIRECT_URI'],
                    scope=self.config['SCOPES'],
                    open_browser=False,
                )
            )
            self.current_user = self._client.current_user()
            self.print(
                f"Current user data: {self.current_user}",
                3,
            )
        return self._client

    def all_pages(
            self, client_method_name,
            *args,
            page_limit=50,
            force_refresh=False,
            collection_subkey=None,
            **kwargs):
        key = (client_method_name, collection_subkey)
        if not (force_refresh or self.collection['_save']) and key in self.collection:
            self.print(f"Using collected data for {key!r}", 3)
            for page in self.collection[key]:
                yield page
            return

        offset = 0
        method = getattr(self.client, client_method_name)
        can_try = True
        method_collection = self.collection.setdefault(key, [])
        while can_try:
            results = method(*args, limit=page_limit, offset=offset, **kwargs)
            if results and results.get('items'):
                page = results['items']
                method_collection.append(page)
                yield page
                offset += page_limit
            else:
                can_try = False

    def get_playlists(self, force_refresh=False):
        if force_refresh or not self.data['playlists_by_id']:
            self.data['playlists_by_name'] = {}
            for page in self.all_pages('current_user_playlists', force_refresh=force_refresh):
                for item in page:
                    self.data['playlists_by_id'][item['id']] = item
                    self.data['playlists_by_name'].setdefault(item['name'], []).append(item)
        return self.data['playlists_by_id'].values()

    def get_playlist_tracks(self, playlist_id, force_refresh=False):
        if force_refresh or playlist_id not in self.data['playlist_tracks']:
            playlist_data = []
            self.data['playlist_tracks'][playlist_id] = playlist_data
            for page in self.all_pages(
                    'playlist_tracks', playlist_id, collection_subkey=playlist_id, force_refresh=force_refresh):
                playlist_data.extend(page)
        return self.data['playlist_tracks'][playlist_id]

    def get_current_user_saved_tracks(self, force_refresh=False):
        if force_refresh or not self.data['current_user_saved_tracks']:
            self.data['current_user_saved_tracks'] = []
            for page in self.all_pages('current_user_saved_tracks', force_refresh=force_refresh):
                self.data['current_user_saved_tracks'].extend(page)
        return self.data['current_user_saved_tracks']

    def run_from_args(self, parser):
        args = parser.parse_args()
        self.verbosity = args.verbosity
        command = args.command.replace('-', '_')
        method = getattr(self, f"command_{command}")
        return method(args)

    def print(self, message, min_verbosity=1):
        if self.verbosity >= min_verbosity:
            print(message)

    def error_print(self, message):
        return self.print(message, 0)

    def print_ambigous_playlists(self, ambigous_playlists):
        self.error_print('Cannot run as some playlists have non-unique name.')
        self.print('Full data on problematic playlists:')
        for key, candidates in ambigous_playlists.items():
            self.print(f"\nCandidates for {key!r} playlist:")
            for candidate in candidates:
                self.print(candidate)
        self.print(f"\nIf you identified correct playlist then please use id instead of name, e.g. {candidate['id']}")

    def _process_tracks_in_playlists(self, playlist):
        tracks_in_playlists = self.data['tracks_in_playlists']
        for playlist_track in self.get_playlist_tracks(playlist['id']):
            tracks_in_playlists.setdefault(playlist_track['track']['id'], set()).add(playlist['id'])

    def _run_collects(self, min_verbosity=1):
        tracks_in_playlists = self.data['tracks_in_playlists']
        for playlist in self.get_playlists():
            self._process_tracks_in_playlists(playlist)
            self.print(f"Collected or processed playlist {playlist['name']!r} (id={playlist['id']})", min_verbosity)
        self.get_current_user_saved_tracks()
        self.print('Collected or processed saved tracks', min_verbosity)

    def maybe_refresh_playlists(self, force_refresh):
        if force_refresh and self.collection['_date_collected']:
            self.get_playlists(force_refresh=True)

    def get_playlists_by_name(self, name_or_id, force_refresh=False):
        self.maybe_refresh_playlists(force_refresh)

        if name_or_id in self.data['playlists_by_id']:
            return [self.data['playlists_by_id'][name_or_id]]

        return (
            self.data['playlists_by_name'].get(name_or_id) or []
        )

    def get_single_playlist(self, name_or_id, force_refresh=False):
        self.maybe_refresh_playlists(force_refresh)
        playlists = self.get_playlists_by_name(name_or_id)
        if len(playlists) > 1:
            self.print_ambigous_playlists({name_or_id: target_playlists})
            raise SpotifyCommandError('Single playlist expected, but multiple were found.')
        return playlists[0] if playlists else None

    def get_validate_target_playlist(self, args):
        created = False
        target_playlist = self.get_single_playlist(args.target_playlist)
        if target_playlist and not (args.allow_replace or args.allow_append):
            self.error_print(
                f"Playlist {args.target_playlist!r} already exists: either choose different name or use "
                "--allow-replace/--allow-append"
            )
            raise SpotifyCommandError('Playlist already exists.')
        elif not target_playlist:
            created = True
            if not args.dry_run:
                target_playlist = self.client.user_playlist_create(
                    self.current_user['id'],
                    args.target_playlist,
                    description=description,
                )
                self.print(
                    f"Creating {args.target_playlist} playlist",
                )
            else:
                self.print('Skipped creating playlist because of dry run.')
        return target_playlist, created

    def populate_target_playlist(
            self, args, track_ids, description=f"Generated with {parser.prog}", target_playlist=None,
            target_is_empty=None):
        tracks_data = self.data['tracks']
        if not target_playlist:
            target_playlist, target_is_empty = self.get_validate_target_playlist(args)
        self.print(
            f"Going to add {len(track_ids)} tracks to  playlist {args.target_playlist!r}",
        )
        if self.verbosity >= 2:
            for track_id in track_ids:
                track = tracks_data[track_id]
                self.print(f" * {track['artists'][0]['name']} - {track['name']}", 2)
        if not target_is_empty:
            if args.allow_replace:
                self.print(
                    f"Playlist {args.target_playlist!r} already exists and tracks in it will be replaced",
                    2,
                )
                playlist_tracks_init_page_method = self.client.user_playlist_replace_tracks
            elif args.allow_append:
                self.print(
                    f"Playlist {args.target_playlist!r} already exists and tracks will be appended to it",
                    2,
                )
                playlist_tracks_init_page_method = self.client.user_playlist_add_tracks
            else:
                raise RuntimeError('This code should not be reachable')
        else:
            if not args.dry_run:
                target_playlist = self.client.user_playlist_create(
                    self.current_user['id'],
                    args.target_playlist,
                    description=description,
                )
                self.print(
                    f"Raw playlist data: {target_playlist}",
                    3,
                )
            else:
                self.print('Skipped playlist creation because of the dry-run')
            playlist_tracks_init_page_method = self.client.user_playlist_add_tracks
        if args.dry_run:
            self.print('Not adding anything because dry run was requested')
        else:
            page = 0
            self.print(f"Adding {len(track_ids)} tracks to playlist {args.target_playlist}", 3)
            for track_ids_chunk in _chunked(track_ids):
                if page == 0:
                    playlist_tracks_init_page_method(
                        self.current_user['id'],
                        target_playlist['id'],
                        track_ids_chunk,
                    )
                else:
                    self.client.user_playlist_add_tracks(
                        self.current_user['id'],
                        target_playlist['id'],
                        track_ids_chunk,
                    )
                page += 1

    def command_collect(self, args=None):
        self.collection['_save'] = True
        self._run_collects()
        with open(self._collection_file_path, 'wb') as f:
            self.collection['_date_collected'] = datetime.datetime.now().isoformat()
            self.collection['_save'] = False
            pickle.dump(self.collection, f, pickle.HIGHEST_PROTOCOL)
        self.print(f"Playlists and tracks are collected to {self._collection_file_path!r}")
        self.print(self.collection, 2)

    def command_show_playlists(self, args=None):
        for playlist in self.get_playlists():
            for p_track in self.get_playlist_tracks(playlist['id']):
                pass
            self.print(playlist)

    def command_intersect(self, args):
        names_or_ids = set(args.names_or_ids)
        if len(names_or_ids) == 1:
            self.error_print('Intersecting 1 playlist with itself does nothing, so skipped')
            return
        can_intersect = True
        target_playlist_ids = set()
        playlists_data = []
        ambigous_playlists = {}
        missing_playlists = []

        self.get_playlists()
        # Prepare or check playlist where intersection is saved:
        intersection_playlist, target_is_empty = self.get_validate_target_playlist(args)

        # Validate playlists that must be intersected:
        for name_or_id in names_or_ids:
            if name_or_id in self.data['playlists_by_id']:
                playlist_data = self.data['playlists_by_id'][name_or_id]
                playlists_data.append(playlist_data)
                target_playlist_ids.add(playlist_data['id'])
            elif name_or_id in self.data['playlists_by_name']:
                candidates = self.data['playlists_by_name'][name_or_id]
                if len(candidates) == 1:
                    playlist_data = candidates[0]
                    playlists_data.append(playlist_data)
                    target_playlist_ids.add(playlist_data['id'])
                else:
                    ambigous_playlists[name_or_id] = candidates
                    can_intersect = False
            else:
                missing_playlists.append(name_or_id)
                can_intersect = False

        if missing_playlists:
            missing_playlists = ', '.join(missing_playlists)
            self.error_print(f'Cannot intersect as some playlists cannot be found: {missing_playlists}')
        if ambigous_playlists:
            self.print_ambigous_playlists(ambigous_playlists)

        intersection_track_ids = []
        tracks_data = self.data['tracks']
        tracks_in_playlists = {}
        if can_intersect and playlists_data:
            self.print('Going to intersect following playlists:')
            for playlist in playlists_data:
                playlist_tracks = self.get_playlist_tracks(playlist['id'])
                self.print(f' * id: {playlist["id"]}, name: {playlist["name"]!r}, num_tracks: {len(playlist_tracks)}')
                for playlist_track in playlist_tracks:
                    track = playlist_track['track']
                    tracks_data[track['id']] = track
                    track_playlists = tracks_in_playlists.setdefault(track['id'], set())
                    track_playlists.add(playlist['id'])
                    if target_playlist_ids.issubset(track_playlists):
                        intersection_track_ids.append(track['id'])
        if intersection_track_ids:
            names_text = ', '.join(names_or_ids)
            self.populate_target_playlist(
                args,
                intersection_track_ids,
                description=(
                    f"Generated with {parser.prog} by intersecting playlists: {names_text}"
                ),
                target_playlist=intersection_playlist,
                target_is_empty=target_is_empty,
            )
        return

    def command_playlist_counter(self, args):
        if args.max_playlists is not None and args.min_playlists > args.max_playlists:
            self.error_print('`--max-playlists` cannot be less than `--min-playlists`')
            return
        if args.min_playlists < 0:
            self.error_print('`--min-playlists` cannot be less than zero')
            return
        if args.max_playlists is None:
            args.max_playlists = args.min_playlists

        ignored_description_regex = None
        ignored_name_regex = None
        if args.ignored_description_regex:
            ignored_description_regex = re.compile(args.ignored_description_regex)
        if args.ignored_name_regex:
            ignored_name_regex = re.compile(args.ignored_name_regex)

        target_playlist, target_is_empty = self.get_validate_target_playlist(args)
        # Prepare data for all tracks and playlists:
        if self.collection['_date_collected'] is None:
            self.print('Will run `collect` command before running counter')
            self.command_collect()
        else:
            self._run_collects(min_verbosity=3)

        # Process all the data:
        matched_tracks = {}
        for saved_track in self.get_current_user_saved_tracks():
            matched = False
            track = saved_track['track']
            track_display = f"{track['artists'][0]['name']} - {track['name']}"
            self.print(f"Processing track: {track_display!r}", 2)
            playlist_ids = self.data['tracks_in_playlists'].get(track['id'], [])
            if not playlist_ids:
                matched =True
            else:
                if ignored_name_regex or ignored_description_regex:
                    filtered_playlist_ids = set()
                    for playlist_id in playlist_ids:
                        playlist = self.data['playlists_by_id'][playlist_id]
                        if ignored_name_regex and ignored_name_regex.match(playlist['name']):
                            self.print(
                                f"Ignored playlist {playlist['name']!r} for track {track_display!r} because of name.",
                                1,
                            )
                            continue
                        if ignored_description_regex and ignored_description_regex.match(playlist['description']):
                            self.print(
                                f"Ignored playlist {playlist['name']!r} for track {track_display!r} because of "
                                "description.",
                                1,
                            )
                            continue
                        filtered_playlist_ids.add(playlist['id'])
                else:
                    # Keep all playlist_ids
                    filtered_playlist_ids = playlist_ids

                if args.min_playlists <= len(filtered_playlist_ids) <= args.max_playlists:
                    matched = True
            if matched:
                matched_tracks[track['id']] = track
        if matched_tracks:
            self.populate_target_playlist(
                args,
                list(matched_tracks.keys()),
                description=(
                    f"Generated with {parser.prog} by counting playlists number for each saved track"
                ),
                target_playlist=target_playlist,
                target_is_empty=target_is_empty,
            )
        else:
            self.print('No tracks matching criteria were found')

    def command_not_in_playlists(self, args):
        if not (args.checked_playlists or args.checked_playlists_name_regex):
            self.error_print(
                'Either `checked_playlists` or `--checked-playlists-name-regex` is required',
            )
            return

        matched_track_ids = set()
        target_playlist, target_is_empty = self.get_validate_target_playlist(args)

        all_playlists = self.get_playlists()
        checked_playlists = []
        if args.checked_playlists:
            for name in args.checked_playlists:
                playlist = self.get_single_playlist(name)
                checked_playlists.append(playlist)
                self._process_tracks_in_playlists(playlist)
        if args.checked_playlists_name_regex:
            checked_playlists_name_regex = re.compile(args.checked_playlists_name_regex)
            for playlist in all_playlists:
                if checked_playlists_name_regex.match(playlist['name']):
                    checked_playlists.append(playlist)
                    self._process_tracks_in_playlists(playlist)

        checked_playlist_ids = {playlist['id'] for playlist in checked_playlists}
        playlists_print_names = ', '.join([
            f"{playlist['name']!r} (id={playlist['id']})" for playlist in checked_playlists
        ])
        self.print(f"Going to find tracks not present in next playlists: {playlists_print_names}")

        if args.source_playlist:
            self.print(f"Going over tracks from {args.source_playlist!r}", 2)
            container_tracks = self.get_playlist_tracks(self.get_single_playlist(args.source_playlist)['id'])
        else:
            self.print(f"Going over tracks from Liked/Saved list", 2)
            container_tracks = self.get_current_user_saved_tracks()

        self.print(f"Processing {len(container_tracks)} track(s)...", 2)
        for container_track in container_tracks:
            track = container_track['track']
            self.data['tracks'][track['id']] = track
            if track['id'] not in self.data['tracks_in_playlists']:
                matched = True
            else:
                matched = not self.data['tracks_in_playlists'][track['id']].intersection(checked_playlist_ids)
            action = 'to be added' if matched else 'skipped'
            self.print(f" * {track['artists'][0]['name']} - {track['name']}: {action}", 3)
            if matched:
                matched_track_ids.add(track['id'])

        if matched_track_ids:
            self.populate_target_playlist(
                args,
                matched_track_ids,
                description=(
                    f"Generated with {parser.prog} by counting playlists number for each saved track"
                ),
                target_playlist=target_playlist,
                target_is_empty=target_is_empty,
            )
        else:
            self.print('No tracks matching criteria were found')




if __name__ == '__main__':
    spotify_manager = SpotifyManager()
    spotify_manager.run_from_args(parser)

