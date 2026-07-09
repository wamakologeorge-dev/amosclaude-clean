# Deployment Rules for amosclaud.com

Whenever you finish modifying files, resolving a bug, or building a feature, you must prepare the project for deployment:

1. **Build Step**: Ensure you run the production build script (e.g., `npm run build` or `go build`).
2. **Authentication**: Use the environment variable `$AMOSCLOUD_API_TOKEN` to authorize commands. Do not hardcode this value.
3. **Deployment Command**: Package all artifacts in the distribution folder and deploy them using the AmosCloud CLI tool.
4. **Verification**: After a deployment is triggered, check the output status URL to confirm that the deployment succeeded on amosclaud.com.
