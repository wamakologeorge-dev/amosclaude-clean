# Google Play Data safety form — draft

**Verify this draft against the production service and final privacy policy before submitting.** It is based on the native Android client code, which uses OkHttp/Gson to call the configured Amosclaud API.

## Collection and handling

- The app collects and transmits **name and email address** when a user registers; it transmits **email address and password** to sign in. The password is sent to authenticate registration/login and is not stored by the app after the request.
- The app transmits **authentication/session data**: the service returns session cookies, which the app stores in SharedPreferences and sends with later requests to keep the user signed in.
- The app transmits and receives **user-generated content** in AI chat: chat messages/prompts and assistant responses, including a chat session ID when applicable.
- The app transmits and receives **app/platform data** needed for requested repository, storage, pipeline, deployment, mail, community, and administrator views (for example repository metadata, storage-object metadata, pipeline/deployment inputs, administrator overview counts/status, mail messages, and community feed/posts).
- The app transmits **user-generated content** when a user uses the relevant account features: AI-chat prompts, community post content, and mail recipient, subject, and message body. It receives the corresponding chat, community, and mail content to display to the signed-in user.
- **Community is user-generated content (UGC) that other users can read.** Any signed-in user can read the public Community feed and create posts. To meet Google Play's User-Generated Content policy, the app provides in-app moderation: users can **report** an objectionable post (transmitted to `POST /api/v1/community/report` with the post id and reason, when the server endpoint is available) and can **block** a post's author (stored locally in SharedPreferences on-device; blocked authors' posts are filtered out of the rendered feed even if the server has no block/mute endpoint of its own). A Community Content Policy screen is reachable from the Community feature.
- The app stores the chosen API URL locally in SharedPreferences. The production default is `https://amosclauds.com`.
- The app has no advertising SDK and the client code shows no third-party sharing or third-party analytics SDK.
- Production communication is over HTTPS, so data is encrypted in transit.
- Session cookies and the API URL are stored locally; Android backup is disabled for the app.

## Suggested Play Console answers

| Play form topic | Draft answer |
|---|---|
| Does your app collect or share required user data types? | **Yes, collects. No, does not share with third parties** (subject to verification of server-side providers). |
| Personal info | **Name** and **email address**: collected for account creation, account management, and app functionality. |
| App activity / user-generated content | **Other user-generated content**: chat prompts/messages, community post content, and mail content, collected for app functionality. The Community feed is a public, other-user-visible UGC surface; the app provides in-app report and block controls and a content policy screen (see Play Console's User-Generated Content policy requirements). |
| App info and performance | Do **not** declare unless the production service independently collects diagnostics/crash data; the Android client code does not include an analytics/crash SDK. |
| Financial info, location, contacts, messages, photos/videos, audio, files/docs, calendar, health, web browsing | **Not collected by this native client**, based on code reviewed. Recheck if server-side behavior changes. |
| Authentication information | Declare as needed in the current Play Console taxonomy for login credentials/session authentication; used for account management and app functionality. |
| Is data encrypted in transit? | **Yes** for the production API (`https://amosclauds.com`). |
| Can users request deletion? | **Yes.** The app has an account-deletion feature. |
| Is data used for advertising, marketing, or shared with third parties? | **No**, based on client code. |

## REQUIRED-BEFORE-SUBMIT

Google Play requires a **web account-deletion URL** for apps that support account creation. Publish and validate:

**https://amosclauds.com/account/delete**

The page must let a user request deletion and clearly identify what is deleted or retained. Enter this URL in Play Console's account deletion section. Do not submit until it is live and accurate.
