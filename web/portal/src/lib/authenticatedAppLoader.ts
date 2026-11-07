let authenticatedAppPromise: Promise<typeof import('../AuthenticatedApp')> | null = null;
let onboardingPagePromise: Promise<typeof import('../pages/Onboarding')> | null = null;

export function loadOnboardingPage() {
  if (!onboardingPagePromise) {
    onboardingPagePromise = import('../pages/Onboarding').catch((error) => {
      onboardingPagePromise = null;
      throw error;
    });
  }

  return onboardingPagePromise;
}

export function loadAuthenticatedApp() {
  if (!authenticatedAppPromise) {
    authenticatedAppPromise = Promise.all([
      import('../AuthenticatedApp'),
      loadOnboardingPage(),
    ])
      .then(([authenticatedApp]) => authenticatedApp)
      .catch((error) => {
        authenticatedAppPromise = null;
        throw error;
      });
  }

  return authenticatedAppPromise;
}
