import { test, expect } from '@playwright/test';

test('public walkthrough works for both audiences and on mobile',async({page})=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/showcase');
  await expect(page.getByRole('heading',{name:'A better application starts with a testable strategy.'})).toBeVisible();
  await page.getByRole('button',{name:'4 Feedback boundary'}).click();
  await expect(page.getByText('PASS / FAIL',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Researcher',exact:true}).click();
  await expect(page.getByText('Rubric + rules + rivals')).toBeVisible();
  await page.screenshot({path:'test-results/showcase-recruiter.png',fullPage:true});
  await page.getByRole('button',{name:'For technical reviewers'}).click();
  await expect(page.getByRole('heading',{name:'Can an agent improve with only pass or fail?'})).toBeVisible();
  await expect(page.getByText('Training records are allowlisted.',{exact:false})).toBeVisible();
  await page.screenshot({path:'test-results/showcase-technical.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:'test-results/showcase-mobile.png',fullPage:true});
  expect(errors).toEqual([]);
});

test('register, train, freeze, test and blinded human review',async({page,context})=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/?view=research#access=standout-e2e-observer');
  // Access-link cleanup may remove the query after initial page selection, but the selected page persists.
  await expect(page.getByRole('heading',{name:'Does the strategy actually learn?'})).toBeVisible();
  await page.getByRole('button',{name:'Create fictional pilot'}).click();
  await expect(page.getByRole('button',{name:'Run training',exact:true})).toBeVisible();
  await expect(page.getByText('No result is precomputed.',{exact:false})).toBeVisible();
  await page.getByRole('button',{name:'Run training',exact:true}).click();
  await expect(page.getByRole('button',{name:'Validate and freeze policies'})).toBeVisible({timeout:20000});
  await page.getByRole('button',{name:'Validate and freeze policies'}).click();
  await expect(page.getByRole('button',{name:'Run held-out test'})).toBeVisible({timeout:20000});
  await expect(page.getByRole('heading',{name:'Frozen policies',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Run held-out test'}).click();
  await expect(page.getByRole('heading',{name:'Test complete. Add an independent review.'})).toBeVisible({timeout:20000});
  await expect(page.getByText('4 / 4 complete',{exact:true})).toBeVisible();
  await expect(page.getByText('95% paired family-cluster percentile bootstrap;', {exact:false})).toBeVisible();
  await page.getByRole('button',{name:'Create blind review link'}).click();
  const path=await page.getByRole('link',{name:'Open reviewer workspace'}).getAttribute('href');
  const reviewer=await context.newPage();await reviewer.goto(path!);
  await expect(reviewer.getByRole('heading',{name:'Independent document review'})).toBeVisible();
  await expect(reviewer.getByText('PRIVATE_CRITIQUE_SENTINEL',{exact:false})).toHaveCount(0);
  for(const k of ['Clarity','Specificity','Credibility','Feasibility'])await reviewer.getByLabel(k,{exact:true}).selectOption('4');
  await reviewer.getByLabel('Would you recommend this submission?').selectOption('yes');
  await reviewer.getByLabel('Evidence for your assessment').fill('The proposal connects its evidence to a bounded and inspectable contribution.');
  await reviewer.getByRole('button',{name:'Save review and continue'}).click();
  await expect(reviewer.getByText('1 / 40 reviewed',{exact:true})).toBeVisible();
  await expect(page.getByText('1 review recorded',{exact:false})).toBeVisible({timeout:8000});
  const dl=page.waitForEvent('download');await page.getByRole('button',{name:'Export complete research trace'}).click();expect((await dl).suggestedFilename()).toMatch(/^research-/);
  await page.screenshot({path:'test-results/research-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:'test-results/research-mobile.png',fullPage:true});
  expect(errors).toEqual([]);
});
