import assert from "node:assert/strict";

/** Exercise dismissal independently of selection, then prove a real pointer selection still works. */
export async function checkComboBoxLifecycle(page, box, list, text, requestsHash) {
  const options = page.locator(`${list} [role=option]:not(:disabled)`);
  const show = async () => {
    await box.fill("");
    await box.fill(text);
    await options.first().waitFor();
    assert.equal(await box.getAttribute("aria-expanded"), "true");
    assert.equal(await box.getAttribute("aria-controls"), list.slice(1));
    assert.equal(await page.locator(list).evaluate((el) => document.body.contains(el) && !document.getElementById("root").contains(el)), true,
      "the controlled list resolves in body outside the app root");
  };
  const closed = async () => {
    await page.waitForFunction((selector) => !document.querySelector(selector), list);
    assert.equal(await box.getAttribute("aria-expanded"), "false");
    assert.equal(await box.getAttribute("aria-activedescendant"), null);
    assert.equal(await page.getByRole("listbox").count(), 0, "no stale listbox remains in body");
  };

  await show();
  await box.press("ArrowDown");
  const address = page.url();
  await box.press("Tab");
  await closed();
  assert.equal(await box.inputValue(), text, "Tab does not select or apply the search");
  assert.equal(page.url(), address);
  assert.equal(await page.evaluate(() => !!document.activeElement?.closest("[role=listbox]")), false, "Tab skips the popup");

  await show();
  await box.press("ArrowDown");
  await box.evaluate((el) => el.blur());
  await closed();

  await show();
  await box.press("ArrowDown");
  // A document click with no preceding focus change exercises the outside-click path independently of blur.
  await page.locator("body").dispatchEvent("click");
  await closed();
  assert.equal(await box.inputValue(), text);
  assert.equal(page.url(), address);

  await show();
  assert.equal(await options.evaluateAll((items) => items.every((item) => item.tabIndex < 0)), true, "options stay out of the Tab sequence");
  await options.first().hover();
  await page.mouse.down();
  assert.equal(await box.evaluate((el) => document.activeElement === el), true, "pointer-down keeps DOM focus on the input");
  await page.mouse.up();
  await closed();
  assert.notEqual(await box.inputValue(), text, "pointer-up selected the option instead of only dismissing it");
  assert.equal(await box.evaluate((el) => document.activeElement === el), true, "selection leaves focus on the input");

  await show();
  // Change the route without blurring/clicking away first: this must exercise unmount, not dismissal.
  await page.evaluate((hash) => { location.hash = hash; }, requestsHash);
  await page.waitForFunction((selector) => !document.querySelector(selector), list);
  assert.equal(await box.count(), 0, "the old tab and its input unmounted");
  assert.equal(await page.getByRole("listbox").count(), 0, "switching tabs removes the body portal");
}
