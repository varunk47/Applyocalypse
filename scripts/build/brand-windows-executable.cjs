// Writes the product icon and version strings into the packaged Windows exe.
//
// electron-builder normally does this with rcedit, but it gates that on
// `signAndEditExecutable`, the same flag that turns on code signing. Turning
// the flag on makes it fetch a signing toolchain whose archive contains macOS
// dylib symlinks, and creating a symlink needs a privilege Windows withholds
// outside Developer Mode, so the extraction fails and the build dies with it.
// Until there is a certificate worth turning signing on for, the branding half
// is done here with resedit, the same library electron-builder itself uses to
// write the asar integrity resource into this exact executable.
//
// Without this the shortcut, the taskbar button, alt-tab, and the Details tab
// of the file properties all show Electron's logo and "Electron" as the name.
const { readFile, writeFile } = require("node:fs/promises");
const { NtExecutable, NtExecutableResource, Resource, Data } = require("resedit");

// Windows version resources are language scoped. 1033 is en-US and 1200 is the
// UTF-16 codepage; Electron ships its own strings under that pair, so reusing
// it replaces them rather than adding a second language nobody reads.
const LANG_EN_US = 1033;
const CODEPAGE_UNICODE = 1200;

/**
 * Version resources hold four 16 bit numbers. A prerelease suffix such as
 * `0.2.0-rc.1` carries no numeric slot, so it is dropped here and survives in
 * the string values, which is where Windows shows it to a person anyway.
 */
const toVersionQuad = (version) => {
  const parts = version.split("-")[0].split(".").map((part) => Number.parseInt(part, 10));
  if (parts.some((part) => !Number.isInteger(part) || part < 0 || part > 0xffff)) {
    throw new Error(`cannot express version "${version}" as a Windows version resource`);
  }
  while (parts.length < 4) {
    parts.push(0);
  }
  return parts;
};

/**
 * @param {object} options
 * @param {string} options.executablePath packaged exe, rewritten in place
 * @param {string} options.iconPath multi resolution .ico
 * @param {string} options.productName
 * @param {string} options.version
 * @param {string} options.description
 * @param {string} options.copyright
 * @param {string} [options.companyName]
 */
const brandWindowsExecutable = async ({
  executablePath,
  iconPath,
  productName,
  version,
  description,
  copyright,
  companyName
}) => {
  const executable = NtExecutable.from(await readFile(executablePath));
  const resource = NtExecutableResource.from(executable);

  // Every frame in the .ico goes in, so Windows picks the right one per surface
  // instead of rescaling one bitmap into a blurry taskbar button.
  const icon = Data.IconFile.from(await readFile(iconPath));
  Resource.IconGroupEntry.replaceIconsForResource(
    resource.entries,
    1,
    LANG_EN_US,
    icon.icons.map((item) => item.data)
  );

  const versionInfoList = Resource.VersionInfo.fromEntries(resource.entries);
  if (versionInfoList.length !== 1) {
    throw new Error(`expected one version resource in ${executablePath}, found ${versionInfoList.length}`);
  }
  const versionInfo = versionInfoList[0];
  const quad = toVersionQuad(version);

  versionInfo.setFileVersion(...quad, LANG_EN_US);
  versionInfo.setProductVersion(...quad, LANG_EN_US);
  versionInfo.setStringValues(
    { lang: LANG_EN_US, codepage: CODEPAGE_UNICODE },
    {
      ProductName: productName,
      FileDescription: description,
      LegalCopyright: copyright,
      InternalName: productName,
      // Electron leaves "electron.exe" here, which is what Task Manager and
      // several enterprise inventory tools report as the running program.
      OriginalFilename: `${productName}.exe`,
      ProductVersion: version,
      FileVersion: version,
      ...(companyName ? { CompanyName: companyName } : {})
    }
  );
  versionInfo.outputToResourceEntries(resource.entries);

  // Rewrites every entry, so the ELECTRONASAR integrity resource written
  // earlier in the pack survives.
  resource.outputResource(executable);
  await writeFile(executablePath, Buffer.from(executable.generate()));
};

module.exports = { brandWindowsExecutable, toVersionQuad };
