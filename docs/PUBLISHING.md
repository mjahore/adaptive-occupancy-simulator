# Repository and HACS installation

Repository: https://github.com/mjahore/adaptive-occupancy-simulator

In HACS, choose **Custom repositories**, enter that URL, select **Integration**, add it and download Adaptive Occupancy Simulator. Restart Home Assistant, then add the integration through Settings → Devices & services. Keep dry run on during setup and validation.

Default HACS-store inclusion is separate and is not required. This repository follows the standard single-integration layout and bundles its native brand icons. Its CI validates tests, formatting, hassfest and HACS metadata. Check the GitHub Actions result for the version you install.

## Maintainer release steps

Run tests on the targeted HA/Python versions, update the manifest version and change notes, push the commit, and check CI. Tag a stable release only after checks pass. HACS can also download the default branch; it does not require ZIP-release packaging for this layout.

Household-specific configuration, Recorder data and personal migration backups do not belong in this public repository. The examples are generic and do not replace a user's complete household scripts.

See the [HACS integration requirements](https://www.hacs.xyz/docs/publish/integration/) and [custom repository instructions](https://www.hacs.xyz/docs/faq/custom_repositories/).
