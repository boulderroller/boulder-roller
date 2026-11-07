type TabFallback = 'Home' | 'Record' | 'Climbs' | 'Profile';

interface BackNavigation {
  canGoBack: () => boolean;
  goBack: () => void;
  reset: (state: any) => void;
}

export function goBackOrReset(
  navigation: BackNavigation,
  fallbackTab: TabFallback,
) {
  if (navigation.canGoBack()) {
    navigation.goBack();
    return;
  }

  navigation.reset({
    index: 0,
    routes: [
      {
        name: 'Tabs',
        params: { screen: fallbackTab },
      },
    ],
  });
}
