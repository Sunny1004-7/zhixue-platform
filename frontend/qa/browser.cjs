const fs = require('fs');

/** Launch the browser selected by the deployment environment.
 *
 * ZHIXING_BROWSER_PATH takes precedence.  On Windows the helper discovers Edge
 * from its standard installation locations; other systems use the Chromium
 * browser installed by Playwright.  This keeps QA scripts portable while
 * allowing a school-managed browser to be selected explicitly.
 */
async function launchBrowser(chromium) {
  const configuredPath = process.env.ZHIXING_BROWSER_PATH;
  if (configuredPath) {
    if (!fs.existsSync(configuredPath)) {
      throw new Error(`ZHIXING_BROWSER_PATH 指向的文件不存在：${configuredPath}`);
    }
    return chromium.launch({ executablePath: configuredPath, headless: true });
  }

  const edgeCandidates = process.platform === 'win32'
    ? [
        `${process.env.PROGRAMFILES || ''}\\Microsoft\\Edge\\Application\\msedge.exe`,
        `${process.env['PROGRAMFILES(X86)'] || ''}\\Microsoft\\Edge\\Application\\msedge.exe`,
        `${process.env.LOCALAPPDATA || ''}\\Microsoft\\Edge\\Application\\msedge.exe`,
      ]
    : [];
  const edgePath = edgeCandidates.find((candidate) => candidate && fs.existsSync(candidate));
  if (edgePath) return chromium.launch({ executablePath: edgePath, headless: true });

  try {
    return await chromium.launch({ headless: true });
  } catch (error) {
    throw new Error(
      '未找到可用浏览器。请运行“npx playwright install chromium”，或通过 ZHIXING_BROWSER_PATH 指定浏览器。',
      { cause: error },
    );
  }
}

module.exports = { launchBrowser };
