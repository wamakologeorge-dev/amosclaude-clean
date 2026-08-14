# Google Play content rating questionnaire — draft

Complete the current IARC/Play questionnaire in Play Console; questions can change. Proposed answers for this native utility/productivity client:

- **App type/category:** Utility / Productivity; AI engineering-platform client.
- **User-generated content / social feed:** **Yes.** The app has a Community feature (`NativeModuleActivity` "community" module) with a public feed (`GET /api/v1/community/feed`) that any signed-in user can read, and any signed-in user can create posts (`POST /api/v1/community/posts`). This is user-generated content and must be declared as such in the questionnaire and in the Data safety form. In-app moderation controls are provided: users can report a post (`POST /api/v1/community/report`) and block a post's author, which hides that author's posts locally on the device going forward. A Community Content Policy is available in-app from the Community screen. AI chat is a separate, private, single-user account feature and is not shared/public content.
- **Violence, gore, weapons, sexual content/nudity, profanity, controlled substances, tobacco, alcohol:** No.
- **Gambling, simulated gambling, contests, or real-money transactions:** No.
- **Horror/fear, medical/health content, mature themes:** No.
- **Location sharing, contacts, camera, microphone, or user-to-user communication:** No.
- **Ads:** No ads.
- **Data collection:** Answer separately and consistently with `data-safety.md`.
- **Target audience:** Not directed to children; select the appropriate non-child audience age groups for the finalized product policy.

Expected outcome: a low/appropriate productivity-app rating, subject to the final Play Console questionnaire and any content presented by the service.
