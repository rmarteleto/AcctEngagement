"""Like most recent post of users in the input file"""
import json
import codecs
import datetime
import time
import os.path
import tenacity
import http

from instagram_private_api import (
    Client, ClientError, ClientLoginError,
    ClientCookieExpiredError, ClientLoginRequiredError,
    __version__ as client_version)

USER_NAME = ''
PASSWORD = ''
SETTINGS_FILE = '.cache'
CONFIG_FILE = 'config.json'

home_count = 200
hashtag_count = 20
hashtag_list = []
ignore_exact = []
ignore_match = []
non_repeat = {}
non_repeat_allowance = 5


def to_json(python_object):
    """Convert python object to json"""
    if isinstance(python_object, bytes):
        return {'__class__': 'bytes',
                '__value__': codecs.encode(python_object, 'base64').decode()}
    raise TypeError(repr(python_object) + ' is not JSON serializable')


def from_json(json_object):
    """Convert json object to python"""
    if '__class__' in json_object and json_object['__class__'] == 'bytes':
        return codecs.decode(json_object['__value__'].encode(), 'base64')
    return json_object


def onlogin_callback(instagram_api, new_settings_file):
    """Instagram login callback function"""
    cache_settings = instagram_api.settings
    with open(new_settings_file, 'w') as outfile:
        json.dump(cache_settings, outfile, default=to_json)
        print('SAVED: {0!s}'.format(new_settings_file))


def load_config_file():
    """Load json config file"""
    with open(CONFIG_FILE, "r") as f:
        data = json.load(f)
        global home_count, hashtag_count, hashtag_list, ignore_exact, ignore_match
        home_count = data["homeCount"]
        hashtag_count = data["hashtagCount"]
        hashtag_list = list(map(lambda x: x["name"], data["hashtagList"]))
        ignore_exact = data["ignoreExact"]
        ignore_match = data["ignoreMatch"]


def skip(n):
    # skip if user name is supposed to be ignored
    if n in ignore_exact:
        print(f"Skipping {n} due to exact")
        return True

    # skip if user name is in ignore_match
    found = False
    for match in ignore_match:
        if match in n:
            ignore_exact.append(n)
            found = True
            break
    if found == True:
        print(f"Skipping {n} due to match")
        return True

    # skip if maximum repeat per user has been reached
    if n in non_repeat: 
        current = non_repeat[n]
        if current >= non_repeat_allowance:
            print(f"Skipping {n} due to allowance")
            return True
        else:
            non_repeat[n] = current + 1
    else:
        non_repeat[n] = 1

    return False

def process_homepage():
    print(f"Starting homepage")
    count = 1
    max_id = ''
    while count < home_count:
        posts = api.feed_timeline(max_id=max_id, count=25)
        #seen = ''
        feed_items = posts["feed_items"]
        num_results = posts["num_results"]
        print(f"Downloaded: {num_results}")
        max_id = posts["next_max_id"]
        for feed_item in feed_items:
            # skip if required data is not in the feed item
            if ("media_or_ad" not in feed_item or 
                "user" not in feed_item["media_or_ad"] or
                "username" not in feed_item["media_or_ad"]["user"] or
                "has_liked" not in feed_item["media_or_ad"] or
                "id" not in feed_item["media_or_ad"]):
                print(f"Skipping due to bad format")
                continue

            id = feed_item["media_or_ad"]["id"]
            username = feed_item["media_or_ad"]["user"]["username"]
            taken = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(feed_item["media_or_ad"]["taken_at"]))

            # skip items that have been liked            
            if feed_item["media_or_ad"]["has_liked"] == True:
                print(f"Skipping post {id} from {username} - {taken}. It is already liked")
                continue

            if skip(username):
                continue
            time.sleep(2)
            api.post_like(id)
            print(f"Liking post {id} from {username} - {taken}. Count: {count}")
            count += 1

            if count > home_count:
                break


def process_hashtags():
    rank_token = Client.generate_uuid()
    total = len(hashtag_list)
    current = 0
    exception = 0
    for hashtag in hashtag_list:
        current += 1
        print('')
        print(f"Starting hashtag: {hashtag} - {current} of {total}")
        count = 1
        liked = 0
        skipped = 0
        max_id = ''
        while count < hashtag_count:
            try:
                feed = api.feed_tag(hashtag, rank_token, max_id=max_id, count=20)
            except (http.client.IncompleteRead):
                print("Exception :(")
                continue

            if "next_max_id" not in feed:
                break

            max_id = feed["next_max_id"]
            items = []

            num_results = feed["num_results"]
            print(f"Downloaded: {num_results}")

            if "items" in feed:
                items += feed["items"]

            if len(items) == 0:
                break

            for item in items:
                # go to next item
                if ("id" not in item or 
                    "has_liked" not in item or
                    "user" not in item or
                    "username" not in item["user"]):
                    continue

                id = item["id"]
                username = item["user"]["username"]
                taken = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(item["taken_at"]))

                # skip items that have been liked            
                if item["has_liked"] == True:
                    liked += 1
                    print(f"Skipping post {id} from {username} - {taken}. It is already liked")

                    # break for loop
                    if liked >= 5:
                        break
                    else:
                        continue

                # skip items that match black list
                if skip(username):
                    skipped += 1

                    if skipped > 50:
                        break
                    else:
                        continue

                time.sleep(4)
                try:
                    api.post_like(id)
                    print(f"Liking post {id} from {username} - {taken}. Count: {count}")
                    count += 1
                    liked = 0
                except (ClientError):
                    exception += 1

                    if exception == 20:
                        exit(9)

                    print(f"Exception on post {id} from {username}.")
                    continue

                if count > hashtag_count:
                    break
            
            # break while loop
            if liked >= 5 or skipped >= 50:
                break


if __name__ == '__main__':

    # check if input exists
    if not os.path.isfile(CONFIG_FILE):
        print(f'{CONFIG_FILE} doesn\'t exist')
        exit(9)

    device_id = None

    try:
        if not os.path.isfile(SETTINGS_FILE):
            print('Unable to find file: {0!s}'.format(SETTINGS_FILE))
            api = Client(USER_NAME, PASSWORD, on_login=lambda x: onlogin_callback(x, SETTINGS_FILE))
        else:
            with open(SETTINGS_FILE) as file_data:
                cached_settings = json.load(file_data, object_hook=from_json)
            print('Reusing settings: {0!s}'.format(SETTINGS_FILE))

            device_id = cached_settings.get('device_id')
            # reuse auth settings
            api = Client(USER_NAME, PASSWORD, settings=cached_settings)
    except (ClientCookieExpiredError, ClientLoginRequiredError) as e:
        print('ClientCookieExpiredError/ClientLoginRequiredError: {0!s}'.format(e))

        # Login expired
        # Do relogin but use default ua, keys and such
        api = Client(
            USER_NAME, PASSWORD,
            device_id=device_id,
            on_login=lambda x: onlogin_callback(x, SETTINGS_FILE))

    except ClientLoginError as e:
        print('ClientLoginError {0!s}'.format(e))
        exit(9)
    except ClientError as e:
        print('ClientError {0!s} (Code: {1:d}, Response: {2!s})' \
              .format(e.msg, e.code, e.error_response))
        exit(9)
    except Exception as e:
        print('Unexpected Exception: {0!s}'.format(e))
        exit(99)

    print('Cookie Expiry: {0!s}' \
          .format(datetime.datetime.fromtimestamp(api.cookie_jar.auth_expires) \
                  .strftime('%Y-%m-%dT%H:%M:%SZ')))

    load_config_file()
    process_homepage()
    process_hashtags()
