# Temporary timing probe for check "7 the Quotas and KPIs": prints the time of each step as T7 lines.
import sys
p=sys.argv[1]
s=open(p).read()
i=s.index('await check("7 the Quotas and KPIs tabs')
j=s.index('console.log(`  ${VIEWS.length} views, 3 widths, 2 themes, ${scans} axe scans`);', i)
body=s[i:j]
rep=[
('''        const { context, page, errors } = await quotaFresh({ user, width, kpi: podKpi });
        await reach(page);''','''        let t = Date.now(); const lap = (what) => { const n = Date.now(); console.log(`T7 ${view} ${width} ${what} ${n - t}`); t = n; };
        const { context, page, errors } = await quotaFresh({ user, width, kpi: podKpi }); lap("fresh");
        await reach(page); lap("reach");'''),
('''          await settle(page);
          assert.equal(await running(page), 0''','''          lap(`${theme} toggle`); await settle(page); lap(`${theme} settle`);
          assert.equal(await running(page), 0'''),
('''          await page.screenshot({ path: join(out, `${view}-${width}-${theme}.png`), fullPage: true });''','''          lap(`${theme} layout`); await page.screenshot({ path: join(out, `${view}-${width}-${theme}.png`), fullPage: true }); lap(`${theme} screenshot`);'''),
('''            const scan = await new AxeBuilder({ page }).analyze();''','''            const scan = await new AxeBuilder({ page }).analyze(); lap(`${theme} axe`);'''),
('''        assert.deepEqual(errors, []);
        await context.close();''','''        assert.deepEqual(errors, []);
        await context.close(); lap("close");'''),
]
for a,b in rep:
    assert a in body, a
    body=body.replace(a,b)
s=s[:i]+body+s[j:]
open(p,'w').write(s)
