import json
import os

from oauth2client.client import flow_from_clientsecrets
from oauth2client.file import Storage
from oauth2client.tools import run_flow

import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
import requests
import youtube_dl

import spotipy
import spotipy.util as util

from exceptions import ResponseException
from secrets import spotify_user_id, spotify_client_id, spotify_client_secret

appScope = 'playlist-read-private playlist-modify-private'

def getAccessToken():
    token = util.prompt_for_user_token(spotify_user_id,
                                         appScope, 
                                         client_id=spotify_client_id, 
                                         client_secret=spotify_client_secret,
                                         redirect_uri='http://127.0.0.1:8080/callback/')
    return token

class CreatePlaylist:
    def __init__(self):
        self.youtube_client = self.get_youtube_client()
        self.all_song_info = {}
        self.spotify_token = getAccessToken()

    def get_youtube_client(self):
        """ Log Into Youtube, Copied from Youtube Data API """
        # Disable OAuthlib's HTTPS verification when running locally.
        # *DO NOT* leave this option enabled in production.
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

        api_service_name = "youtube"
        api_version = "v3"
        client_secrets_file = "client_secret.json"

        # Get credentials and create an API client
        MISSING_CLIENT_SECRETS_MESSAGE = """WARNING: Please configure OAuth 2.0"""
        flow = flow_from_clientsecrets(client_secrets_file,
            scope=["https://www.googleapis.com/auth/youtube.readonly"],
            message=MISSING_CLIENT_SECRETS_MESSAGE)

        storage = Storage("%s-oauth2.json" % os.sys.argv[0])
        credentials = storage.get()

        if credentials is None or credentials.invalid:
            credentials = run_flow(flow, storage)

        # from the Youtube DATA API
        youtube_client = googleapiclient.discovery.build(
            api_service_name, api_version, credentials=credentials)

        return youtube_client

    def get_liked_videos(self):
        """Grab Our Liked Videos & Create A Dictionary Of Important Song Information"""
        request = self.youtube_client.videos().list(
            part="snippet,contentDetails,statistics",
            myRating="like"
        )
        response = request.execute()

        # Read cache file and check if the cached value is the most recent. If that's not the case, the file will be updated with the new value
        if not os.path.isfile("cache.txt"):
            open("cache.txt","w+").close()

        cache_file = open("cache.txt","r+")
        cached_recent_liked_video = cache_file.read()
        most_recent_liked_video = response["items"][0]['id']

        if(cached_recent_liked_video == most_recent_liked_video):
            return
        else:
            cache_file.truncate(0)
            cache_file.write(most_recent_liked_video)
        cache_file.close()

        # collect each video and get important information
        for item in response["items"]:
            video_title = item["snippet"]["title"]

            if item["id"] == cached_recent_liked_video:
                break

            youtube_url = "https://www.youtube.com/watch?v={}".format(
                item["id"])

            # use youtube_dl to collect the song name & artist name
            video = youtube_dl.YoutubeDL({}).extract_info(
                youtube_url, download=False)
            song_name = video["track"]
            artist = video["artist"]

            if song_name is not None and artist is not None:
                tempSpotifyUri = self.get_spotify_uri(song_name, artist)
                if tempSpotifyUri is not "":
                    # save all important info and skip any missing song and artist
                    self.all_song_info[video_title] = {
                        "youtube_url": youtube_url,
                        "song_name": song_name,
                        "artist": artist,
                        # add the uri, easy to get song to put into playlist
                        "spotify_uri": tempSpotifyUri
                    }

    def create_playlist(self):
        """Create A New Playlist"""
        request_body = json.dumps({
            "name": "Youtube Liked Vids",
            "description": "All Liked Youtube Videos",
            "public": False
        })

        #Retrieves all of the playlists of the user and searches for the correct one
        get_playlists_query = "https://api.spotify.com/v1/users/{}/playlists".format(
            spotify_user_id)
        
        response_playlists_query = requests.get(
            get_playlists_query,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(self.spotify_token)
            }
        )
        playlists_response_json = response_playlists_query.json()

        for item in playlists_response_json['items']:
            if item['name'] == "Youtube Liked Vids":
                return item['id']

        #Se debe de truncar el fichero de nuevo
        if os._exists("cache.txt"):
            os.remove("cache.txt")

        #If the playlist is not found, we need to create it
        query = "https://api.spotify.com/v1/users/{}/playlists".format(
            spotify_user_id)
        response = requests.post(
            query,
            data=request_body,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(self.spotify_token)
            }
        )
        response_json = response.json()

        # playlist id
        return response_json["id"]

    def get_spotify_uri(self, song_name, artist):
        """Search For the Song"""
        query = "https://api.spotify.com/v1/search?query=track%3A{}+artist%3A{}&type=track&offset=0&limit=20".format(
            song_name,
            artist
        )
        response = requests.get(
            query,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(self.spotify_token)
            }
        )
        response_json = response.json()
        songs = response_json["tracks"]["items"]

        # Only use the first song, if the list contains elements
        try:
            uri = songs[0]["uri"]
        except Exception:
            uri = ""
            print("No URIs found for this result")

        return uri

    def add_song_to_playlist(self):
        """Add all liked songs into a new Spotify playlist"""

        # create a new playlist
        playlist_id = self.create_playlist()

        # populate dictionary with our liked songs
        self.get_liked_videos()

        # collect all of uri
        uris = [info["spotify_uri"]
                for song, info in self.all_song_info.items()]

        # add all songs into new playlist
        request_data = json.dumps(uris)

        query = "https://api.spotify.com/v1/playlists/{}/tracks".format(
            playlist_id)

        response = requests.post(
            query,
            data=request_data,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(self.spotify_token)
            }
        )

        # check for valid response status
        if response.status_code == 400:
            print("Song cannot be found on Spotify")
        elif response.status_code != 201:
            raise ResponseException(response.status_code)

        response_json = response.json()
        return response_json


if __name__ == '__main__':
    cp = CreatePlaylist()
    cp.add_song_to_playlist()
