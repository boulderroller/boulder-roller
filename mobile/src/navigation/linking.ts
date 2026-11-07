import type { LinkingOptions, NavigatorScreenParams } from '@react-navigation/native';
import * as ExpoLinking from 'expo-linking';

type TabParamList = {
  Home: undefined;
  Record: undefined;
  Climbs: undefined;
  Profile: undefined;
};

type RootStackParamList = {
  Tabs: NavigatorScreenParams<TabParamList>;
  RideDetail: { rideId?: string; serverRideId?: string };
  ClimbDetail: { climbId: string };
  ClimbLeaderboard: { climbId: string };
  RiderDetail: { identifier: string };
  Search: undefined;
  Notifications: undefined;
  PrivacySettings: undefined;
  NotificationPreferences: undefined;
  EditProfile: undefined;
  MyReports: undefined;
};

export const linking: LinkingOptions<RootStackParamList> = {
  prefixes: [
    ExpoLinking.createURL('/'),
    'boulderroller://',
    'com.boulderroller.app://',
    'https://boulderroller.app',
    'https://www.boulderroller.app',
  ],
  config: {
    screens: {
      Tabs: {
        screens: {
          Home: 'home',
          Record: 'record',
          Climbs: 'climbs',
          Profile: 'profile',
        },
      },
      RideDetail: {
        path: 'rides/:rideId',
        alias: ['ride/:rideId', 'activities/:rideId'],
      },
      ClimbDetail: {
        path: 'climbs/:climbId',
        alias: ['climb/:climbId', 'segments/:climbId', 'climbs/:climbId/local-legend'],
      },
      ClimbLeaderboard: 'climbs/:climbId/leaderboard',
      RiderDetail: {
        path: 'riders/:identifier',
        alias: ['rider/:identifier'],
      },
      Search: 'search',
      Notifications: 'notifications',
      PrivacySettings: 'settings/privacy',
      NotificationPreferences: 'settings/notifications',
      EditProfile: 'settings/profile',
      MyReports: 'settings/reports',
    },
  },
};
