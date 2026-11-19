// Embed icon and Windows PE metadata directly so unsigned local builds do not depend on winCodeSign.
const fs = require("node:fs");
const path = require("node:path");

exports.default = async function afterPack(context) {
  if (context.electronPlatformName !== "win32") return;

  const appInfo = context.packager.appInfo;
  const exeName = `${appInfo.productFilename}.exe`;
  const exePath = path.join(context.appOutDir, exeName);
  const iconPath = path.resolve(__dirname, "..", "resources", "icon.ico");

  if (!fs.existsSync(exePath)) {
    throw new Error(`afterPack: executable not found at ${exePath}`);
  }
  if (!fs.existsSync(iconPath)) {
    throw new Error(`afterPack: icon not found at ${iconPath}`);
  }

  const version = appInfo.shortVersion || appInfo.version || "0.1.0";
  const productVersion = appInfo.shortVersionWindows || `${version}.0`;
  const { rcedit } = await import("rcedit");

  await rcedit(exePath, {
    icon: iconPath,
    "file-version": productVersion,
    "product-version": productVersion,
    "version-string": {
      ProductName: appInfo.productName || "Whitz",
      FileDescription: appInfo.description || appInfo.productName || "Whitz",
      CompanyName: appInfo.companyName || "Whitz",
      LegalCopyright: appInfo.copyright || "Copyright © 2026 Whitz",
      InternalFilename: appInfo.productFilename || "Whitz",
      OriginalFilename: exeName,
    },
  });
};
