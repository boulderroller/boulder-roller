const slides = Array.from(document.querySelectorAll('.slide'));
const progressBar = document.getElementById('progressBar');
const titleEl = document.getElementById('slideTitle');
const sectionEl = document.getElementById('slideSection');
const counterEl = document.getElementById('slideCounter');
const prevBtn = document.getElementById('prevBtn');
const nextBtn = document.getElementById('nextBtn');
const fullscreenBtn = document.getElementById('fullscreenBtn');
const sectionTags = Array.from(document.querySelectorAll('.tag[data-section]'));

let currentIndex = Math.max(0, slides.findIndex((slide) => slide.classList.contains('is-active')));

// Section jump
sectionTags.forEach((tag) => {
  tag.style.cursor = 'pointer';
  tag.addEventListener('click', () => {
    const targetSection = tag.dataset.section;
    const targetIndex = slides.findIndex((slide) => slide.dataset.section === targetSection);
    if (targetIndex >= 0) {
      showSlide(targetIndex);
    }
  });
});

const isStackedLayout = () => window.matchMedia('(max-width: 900px)').matches;

const applyAriaVisibility = () => {
  if (isStackedLayout()) {
    slides.forEach((slide) => slide.setAttribute('aria-hidden', 'false'));
    return;
  }
  slides.forEach((slide, index) => {
    slide.setAttribute('aria-hidden', index === currentIndex ? 'false' : 'true');
  });
};

const updateHud = () => {
  const total = slides.length;
  const slide = slides[currentIndex];
  const title = slide?.dataset.title || `Slide ${currentIndex + 1}`;
  const section = slide?.dataset.section || '';
  if (titleEl) titleEl.textContent = title;
  if (sectionEl) sectionEl.textContent = section;
  if (counterEl) counterEl.textContent = `${currentIndex + 1} / ${total}`;
  sectionTags.forEach((tag) => tag.classList.toggle('is-active', tag.dataset.section === section));
  if (progressBar) {
    progressBar.style.width = `${((currentIndex + 1) / total) * 100}%`;
  }
};

const showSlide = (nextIndex) => {
  if (nextIndex < 0 || nextIndex >= slides.length || nextIndex === currentIndex) return;
  slides[currentIndex].classList.remove('is-active');
  currentIndex = nextIndex;
  slides[currentIndex].classList.add('is-active');
  applyAriaVisibility();
  updateHud();

  // On mobile/tablet (stacked layout), scroll to the slide
  if (isStackedLayout()) {
    slides[currentIndex].scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
};

const toggleFullscreen = () => {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen?.();
  } else {
    document.exitFullscreen?.();
  }
};

const markReady = () => {
  document.body.classList.add('is-ready');
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', markReady);
} else {
  markReady();
}

if (prevBtn) prevBtn.addEventListener('click', () => showSlide(currentIndex - 1));
if (nextBtn) nextBtn.addEventListener('click', () => showSlide(currentIndex + 1));
if (fullscreenBtn) fullscreenBtn.addEventListener('click', toggleFullscreen);

const isFormField = (target) => {
  if (!target) return false;
  const tag = target.tagName?.toLowerCase();
  return tag === 'input' || tag === 'textarea' || tag === 'select';
};

// Presenter mode
let presenterMode = false;
const presenterOverlay = document.createElement('div');
presenterOverlay.className = 'presenter-overlay';
presenterOverlay.innerHTML = `
  <div class="presenter-panel presenter-current">
    <div class="presenter-label">Current Slide</div>
    <div class="presenter-preview" id="presenterCurrent"></div>
  </div>
  <div class="presenter-panel presenter-next">
    <div class="presenter-label">Next Slide</div>
    <div class="presenter-preview" id="presenterNext"></div>
  </div>
  <div class="presenter-panel presenter-notes">
    <div class="presenter-label">Speaker Notes</div>
    <div class="presenter-notes-content" id="presenterNotes">No notes for this slide.</div>
  </div>
  <div class="presenter-controls">
    <span id="presenterCounter"></span>
    <button id="presenterClose">Exit (P)</button>
  </div>
`;
document.body.appendChild(presenterOverlay);

const speakerNotes = {
  'The Gap': 'Creator economy framing. Everyone gets this. Sets up the injustice before the solution.',
  'Hook': 'Now the hill analogy lands. They understand the gap, now show the fix.',
  'The Layer': 'High concept. We are infrastructure, not an app. Additive, not replacement.',
  'The Problem': 'Pain points everyone understands. Platform fragility is real.',
  'How It Works': 'Three steps only. If they get this, they get the product.',
  'The Tokens': 'Define CAL and DUNG before showing them. Airline miles analogy.',
  'BeetleCard': 'The beetle absorbs complexity. One card = one identity.',
  'Perpetual': 'Key differentiator. No resets. Early advantage compounds forever.',
  'Who Earns': 'Four roles. Click through each. Everyone has a path.',
  'Early Access': 'Points period explanation. Low risk, high optionality.',
  'Who Gets Paid': 'Performance first, then backers, then soigneurs. Clear hierarchy.',
  'Earnings Flow': 'Simplified CAL distribution. No formulas needed here.',
  'Product Walkthrough': 'Demo feel. Click through steps.',
  'Soigneur': 'Earned through effort, not capital. Keeper of the climb.',
  'Token Supply': 'Standard allocation. Note community-first.',
  'Go-To-Market': 'Serious athletes first, then power users, then mass market.',
  'Anti-Cheat': 'Hardware + community. Cost to cheat exceeds reward.',
  'Economic Engine': 'Fees fund the system. Each has a purpose. No gotchas.',
  'Moat': 'Four layers. Each compounds. Hard to replicate.',
  "What's Next": 'Near term vs post-launch. No specific dates.',
  'Close': 'End with the ask. Join early, compound forever.'
};

const updatePresenterView = () => {
  const currentSlide = slides[currentIndex];
  const nextSlide = slides[currentIndex + 1];
  const currentTitle = currentSlide?.dataset.title || '';
  const nextTitle = nextSlide?.dataset.title || 'End of deck';

  const presenterCurrent = document.getElementById('presenterCurrent');
  const presenterNext = document.getElementById('presenterNext');
  const presenterNotes = document.getElementById('presenterNotes');
  const presenterCounter = document.getElementById('presenterCounter');

  if (presenterCurrent) presenterCurrent.textContent = currentTitle;
  if (presenterNext) presenterNext.textContent = nextTitle;
  if (presenterNotes) presenterNotes.textContent = speakerNotes[currentTitle] || 'No notes for this slide.';
  if (presenterCounter) presenterCounter.textContent = `${currentIndex + 1} / ${slides.length}`;
};

const togglePresenter = () => {
  presenterMode = !presenterMode;
  presenterOverlay.classList.toggle('is-active', presenterMode);
  if (presenterMode) {
    updatePresenterView();
  }
};

document.getElementById('presenterClose')?.addEventListener('click', togglePresenter);

document.addEventListener('keydown', (event) => {
  if (isFormField(event.target)) return;
  if (event.key === 'ArrowRight' || event.key === 'PageDown' || event.key === ' ') {
    event.preventDefault();
    showSlide(currentIndex + 1);
    if (presenterMode) updatePresenterView();
  }
  if (event.key === 'ArrowLeft' || event.key === 'PageUp') {
    event.preventDefault();
    showSlide(currentIndex - 1);
    if (presenterMode) updatePresenterView();
  }
  if (event.key === 'f' || event.key === 'F') {
    event.preventDefault();
    toggleFullscreen();
  }
  if (event.key === 'p' || event.key === 'P') {
    event.preventDefault();
    togglePresenter();
  }
});

let touchStartX = null;

document.addEventListener('touchstart', (event) => {
  if (event.touches.length === 1) {
    touchStartX = event.touches[0].clientX;
  }
});

document.addEventListener('touchend', (event) => {
  if (touchStartX === null) return;
  const endX = event.changedTouches[0].clientX;
  const delta = touchStartX - endX;
  if (Math.abs(delta) > 50) {
    showSlide(delta > 0 ? currentIndex + 1 : currentIndex - 1);
  }
  touchStartX = null;
});

// Role content (Who Earns slide)
const roleContent = {
  rider: {
    title: 'Rider',
    badge: 'Earn from effort',
    copy: 'Ride hard. Upload proofs. Get paid.',
    bullets: [
      'Every ride earns based on effort',
      'Earnings flow into climb vaults you crossed',
      'Faster times = bigger share of the pot',
    ],
  },
  mapper: {
    title: 'Mapper',
    badge: 'Build the map',
    copy: 'We start with no vaults. You create them.',
    bullets: [
      'Earn clout for creating climb vaults',
      'Founder badge for discoverers',
      'Permanent on-chain record of your claim',
    ],
  },
  staker: {
    title: 'Backer',
    badge: 'Passive income',
    copy: 'Back climbs. Earn when others ride.',
    bullets: [
      'Lock CAL into any climb vault',
      'Earn share of traffic',
      'Popular routes pay better',
    ],
  },
  legend: {
    title: 'Soigneur',
    badge: 'Keeper of the climb',
    copy: 'One soigneur per vault. Earned through completions.',
    bullets: [
      'Set description, curate the climb',
      'Report bad data, flag suspicious rides',
      'Earn DUNG from every payout',
    ],
  },
};

const roleButtons = Array.from(document.querySelectorAll('[data-role]'));
const roleTitle = document.getElementById('roleTitle');
const roleBadge = document.getElementById('roleBadge');
const roleCopy = document.getElementById('roleCopy');
const roleBullets = document.getElementById('roleBullets');

const setRole = (roleKey) => {
  const data = roleContent[roleKey];
  if (!data) return;
  roleButtons.forEach((button) => button.classList.toggle('is-active', button.dataset.role === roleKey));
  if (roleTitle) roleTitle.textContent = data.title;
  if (roleBadge) roleBadge.textContent = data.badge;
  if (roleCopy) roleCopy.textContent = data.copy;
  if (roleBullets) {
    roleBullets.innerHTML = '';
    data.bullets.forEach((text) => {
      const item = document.createElement('li');
      item.textContent = text;
      roleBullets.appendChild(item);
    });
  }
};

roleButtons.forEach((button) => {
  button.addEventListener('click', () => setRole(button.dataset.role));
});

// Product walkthrough (simplified)
const walkthrough = [
  {
    title: 'Upload ride',
    copy: 'Drop a GPX/FIT file or connect your tracker.',
    mockHtml: `<div class="mock-content">
      <div class="mock-row"><span class="mock-icon">📁</span>morning_ride.fit<span class="mock-badge">VERIFIED</span></div>
      <div class="mock-row"><span class="mock-icon">⏱️</span>Duration<span class="mock-value">1:42:15</span></div>
      <div class="mock-row"><span class="mock-icon">📏</span>Distance<span class="mock-value">45.2 km</span></div>
    </div>`,
  },
  {
    title: 'Verify + Earn',
    copy: 'We verify power data and calculate your earnings.',
    mockHtml: `<div class="mock-content">
      <div class="mock-row"><span class="mock-icon">⚡</span>Effort verified<span class="mock-badge">REAL WATTS</span></div>
      <div class="mock-row"><span class="mock-icon">✨</span>Earned<span class="mock-value">+82 points</span></div>
    </div>`,
  },
  {
    title: 'Pick vaults',
    copy: 'Stake earnings in the climbs you believe in.',
    mockHtml: `<div class="mock-content">
      <div class="mock-row"><span class="mock-icon">⛰️</span>Flagstaff<span class="mock-value">Stake →</span></div>
      <div class="mock-row"><span class="mock-icon">🏔️</span>Sunshine<span class="mock-value">Stake →</span></div>
      <div class="mock-row"><span class="mock-icon">🌄</span>Super Flag<span class="mock-value">Stake →</span></div>
    </div>`,
  },
  {
    title: 'Leaderboard',
    copy: 'Your best time lives forever. Top riders earn most.',
    mockHtml: `<div class="mock-content">
      <div class="mock-row"><span class="mock-icon">🥇</span>#1 pro_climber<span class="mock-value">12:34</span></div>
      <div class="mock-row"><span class="mock-icon">🥈</span>#2 hill_hunter<span class="mock-value">12:51</span></div>
      <div class="mock-row" style="background: rgba(183, 110, 44, 0.2);"><span class="mock-icon">🥉</span>#3 you<span class="mock-value">13:02</span></div>
    </div>`,
  },
  {
    title: 'Claim rewards',
    copy: 'Stakers and top riders get paid from traffic.',
    mockHtml: `<div class="mock-content">
      <div class="mock-row"><span class="mock-icon">💎</span>Your stake<span class="mock-value">1,200</span></div>
      <div class="mock-row"><span class="mock-icon">📊</span>Pool share<span class="mock-value">2.4%</span></div>
      <div class="mock-row"><span class="mock-icon">🪲</span>Claimable<span class="mock-badge">89 DUNG</span></div>
    </div>`,
  },
];

const walkButtons = Array.from(document.querySelectorAll('[data-walk]'));
const walkMock = document.getElementById('walkMock');
const walkTitle = document.getElementById('walkTitle');
const walkCopy = document.getElementById('walkCopy');

const setWalk = (index) => {
  const data = walkthrough[index];
  if (!data) return;
  walkButtons.forEach((button) => button.classList.toggle('is-active', Number(button.dataset.walk) === index));
  if (walkMock) walkMock.innerHTML = data.mockHtml;
  if (walkTitle) walkTitle.textContent = data.title;
  if (walkCopy) walkCopy.textContent = data.copy;
};

walkButtons.forEach((button) => {
  button.addEventListener('click', () => setWalk(Number(button.dataset.walk)));
});

// Fee phases
const feePhases = [
  { burn: 30, pol: 20, treasury: 50 },
  { burn: 40, pol: 25, treasury: 35 },
  { burn: 60, pol: 25, treasury: 15 },
];

const feeButtons = Array.from(document.querySelectorAll('[data-fee]'));
const feeBurn = document.getElementById('feeBurn');
const feePol = document.getElementById('feePol');
const feeTreasury = document.getElementById('feeTreasury');

const setFeePhase = (index) => {
  const phase = feePhases[index];
  if (!phase) return;
  feeButtons.forEach((button) => button.classList.toggle('is-active', Number(button.dataset.fee) === index));
  if (feeBurn) feeBurn.textContent = `${phase.burn}%`;
  if (feePol) feePol.textContent = `${phase.pol}%`;
  if (feeTreasury) feeTreasury.textContent = `${phase.treasury}%`;
};

feeButtons.forEach((button) => {
  button.addEventListener('click', () => setFeePhase(Number(button.dataset.fee)));
});

// Moat content (simplified labels)
const moatContent = [
  {
    title: 'Data moat',
    copy: 'Permanent on-chain map of geographic assets. Compounds over time. Hard to replicate quickly.',
  },
  {
    title: 'Economic moat',
    copy: 'Revenue sharing that incumbents can\'t match. Switching means leaving money on the table.',
  },
  {
    title: 'Hardware moat',
    copy: 'Power meters cost $300-$1,000+. Device registration required. FTP test standard. You can\'t fake fitness.',
  },
  {
    title: 'Cultural moat',
    copy: 'Cycling + crypto community. Beetle identity. Can\'t be manufactured by a corporate.',
  },
];

const moatButtons = Array.from(document.querySelectorAll('[data-moat]'));
const moatTitle = document.getElementById('moatTitle');
const moatCopy = document.getElementById('moatCopy');

const setMoat = (index) => {
  const data = moatContent[index];
  if (!data) return;
  moatButtons.forEach((button) => button.classList.toggle('is-active', Number(button.dataset.moat) === index));
  if (moatTitle) moatTitle.textContent = data.title;
  if (moatCopy) moatCopy.textContent = data.copy;
};

moatButtons.forEach((button) => {
  button.addEventListener('click', () => setMoat(Number(button.dataset.moat)));
});

window.addEventListener('resize', () => {
  applyAriaVisibility();
});

const initializeDeck = () => {
  updateHud();
  applyAriaVisibility();
  setRole('rider');
  setWalk(0);
  setFeePhase(0);
  setMoat(0);
};

requestAnimationFrame(initializeDeck);
