import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import * as ImagePicker from 'expo-image-picker';
import * as Sentry from '@sentry/react-native';

import { api, ApiError, type User } from '../lib/api';
import DetailHeader from '../components/detail/DetailHeader';
import DetailModule from '../components/detail/DetailModule';
import { ErrorBanner } from '../components/ErrorBanner';
import RiderAvatar from '../components/rider/RiderAvatar';
import { goBackOrReset } from '../navigation/backNavigation';
import { prepareNativeImageUpload } from '../lib/imageUpload';

export default function EditProfileScreen() {
  const navigation = useNavigation();
  const [user, setUser] = useState<User | null>(null);
  const [displayName, setDisplayName] = useState('');
  const [username, setUsername] = useState('');
  const [bio, setBio] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [avatarBusy, setAvatarBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const profile = await api.getMe();
      setUser(profile);
      setDisplayName(profile.displayName ?? '');
      setUsername(profile.username ?? '');
      setBio(profile.bio ?? '');
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err);
      } else {
        setError(new ApiError('Unexpected error', 'unknown'));
        Sentry.captureException(err);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleSave = useCallback(async () => {
    if (saving) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updateProfile({
        displayName: displayName.trim() || undefined,
        username: username.trim() || undefined,
        bio: bio.trim() || undefined,
      });
      setUser(updated);
      Alert.alert('Profile saved', 'Your rider profile is updated.');
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err);
      } else {
        setError(new ApiError('Unexpected error', 'unknown'));
        Sentry.captureException(err);
      }
    } finally {
      setSaving(false);
    }
  }, [bio, displayName, saving, username]);

  const handleChangeAvatar = useCallback(async () => {
    if (avatarBusy) return;
    setAvatarBusy(true);
    setError(null);
    try {
      const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!permission.granted) {
        Alert.alert('Photo access needed', 'Allow photo access to update your profile photo.');
        return;
      }

      const picked = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        allowsEditing: true,
        aspect: [1, 1],
        quality: 1,
        exif: false,
      });
      if (picked.canceled || !picked.assets[0]) return;

      const prepared = await prepareNativeImageUpload(picked.assets[0], {
        fileNamePrefix: 'rider-avatar',
        maxDimension: 1024,
        maxBytes: 2 * 1024 * 1024,
      });
      const updated = await api.uploadAvatar(prepared);
      setUser(updated);
      Alert.alert('Profile photo updated');
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err);
      } else {
        Sentry.captureException(err);
      }
      Alert.alert('Photo upload failed', err instanceof Error ? err.message : 'Please try another image.');
    } finally {
      setAvatarBusy(false);
    }
  }, [avatarBusy]);

  const handleRemoveAvatar = useCallback(async () => {
    if (avatarBusy || !user?.avatarUrl) return;
    setAvatarBusy(true);
    setError(null);
    try {
      const updated = await api.deleteAvatar();
      setUser(updated);
      Alert.alert('Profile photo removed');
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err);
      } else {
        Sentry.captureException(err);
      }
      Alert.alert('Could not remove photo', err instanceof Error ? err.message : 'Please try again.');
    } finally {
      setAvatarBusy(false);
    }
  }, [avatarBusy, user?.avatarUrl]);

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <DetailHeader
          backLabel="Profile"
          title="Edit Profile"
          subtitle={user?.wallet ? `${user.wallet.slice(0, 6)}...${user.wallet.slice(-4)}` : 'Rider profile'}
          onBack={() => goBackOrReset(navigation, 'Profile')}
        />

        {error ? (
          <ErrorBanner
            message={error.retryable ? 'Connection issue' : 'Unable to save profile'}
            onRetry={error.retryable ? load : undefined}
            onDismiss={() => setError(null)}
          />
        ) : null}

        {loading ? (
          <View style={styles.center}>
            <ActivityIndicator size="large" color="#e5e5e5" />
          </View>
        ) : (
          <DetailModule title="Rider identity" subtitle="Shown on public profile, feed, and ride surfaces">
            <Text style={styles.label}>Display name</Text>
            <TextInput
              value={displayName}
              onChangeText={setDisplayName}
              placeholder="Display name"
              placeholderTextColor="#666666"
              style={styles.input}
            />
            <Text style={styles.label}>Username</Text>
            <TextInput
              value={username}
              onChangeText={setUsername}
              placeholder="username"
              placeholderTextColor="#666666"
              autoCapitalize="none"
              style={styles.input}
            />
            <Text style={styles.label}>Bio</Text>
            <TextInput
              value={bio}
              onChangeText={setBio}
              placeholder="Short rider bio"
              placeholderTextColor="#666666"
              multiline
              style={[styles.input, styles.bioInput]}
            />
            {user ? (
              <View style={styles.avatarRow}>
                <RiderAvatar identity={user} size={46} />
                <View style={styles.avatarCopy}>
                  <Text style={styles.label}>Profile photo</Text>
                  <Text style={styles.avatarNote}>{user.avatarUrl ? 'Synced' : 'Not set'}</Text>
                  <View style={styles.avatarActions}>
                    <TouchableOpacity
                      style={[styles.avatarButton, avatarBusy && styles.disabledButton]}
                      onPress={handleChangeAvatar}
                      disabled={avatarBusy}
                      activeOpacity={0.84}
                      testID="edit-profile-avatar-change"
                    >
                      <Text style={styles.avatarButtonText}>{avatarBusy ? 'Working' : user.avatarUrl ? 'Change' : 'Upload'}</Text>
                    </TouchableOpacity>
                    {user.avatarUrl ? (
                      <TouchableOpacity
                        style={[styles.avatarButton, styles.avatarButtonDanger, avatarBusy && styles.disabledButton]}
                        onPress={handleRemoveAvatar}
                        disabled={avatarBusy}
                        activeOpacity={0.84}
                        testID="edit-profile-avatar-remove"
                      >
                        <Text style={[styles.avatarButtonText, styles.avatarButtonDangerText]}>Remove</Text>
                      </TouchableOpacity>
                    ) : null}
                  </View>
                </View>
              </View>
            ) : null}
            <TouchableOpacity
              style={[styles.saveButton, saving && styles.disabledButton]}
              onPress={handleSave}
              disabled={saving}
              activeOpacity={0.84}
              testID="edit-profile-save"
            >
              <Text style={styles.saveText}>{saving ? 'Saving' : 'Save profile'}</Text>
            </TouchableOpacity>
          </DetailModule>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0a0a',
  },
  scroll: {
    padding: 20,
    paddingBottom: 32,
  },
  center: {
    paddingVertical: 48,
    alignItems: 'center',
  },
  label: {
    color: '#858585',
    fontSize: 12,
    fontWeight: '700',
    textTransform: 'uppercase',
  },
  input: {
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#2a2a2a',
    color: '#ededed',
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 14,
    backgroundColor: '#101010',
  },
  bioInput: {
    minHeight: 84,
    textAlignVertical: 'top',
  },
  avatarRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  avatarCopy: {
    gap: 4,
    flex: 1,
  },
  avatarNote: {
    color: '#b8b8b8',
    fontSize: 13,
    fontWeight: '700',
  },
  avatarActions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 6,
  },
  avatarButton: {
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#3b3320',
    backgroundColor: '#171309',
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  avatarButtonDanger: {
    borderColor: '#3f1d1d',
    backgroundColor: '#1a0f0f',
  },
  avatarButtonText: {
    color: '#d0af48',
    fontSize: 12,
    fontWeight: '800',
  },
  avatarButtonDangerText: {
    color: '#e08f7d',
  },
  saveButton: {
    alignSelf: 'flex-start',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#3b3320',
    backgroundColor: '#171309',
    paddingHorizontal: 14,
    paddingVertical: 10,
    marginTop: 4,
  },
  disabledButton: {
    opacity: 0.55,
  },
  saveText: {
    color: '#d0af48',
    fontSize: 13,
    fontWeight: '700',
  },
});
