import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  RefreshControl,
  ActivityIndicator,
  Alert,
  Linking,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from 'expo-router';
import * as ExpoLinking from 'expo-linking';

import { useAuth } from '../../src/AuthContext';
import { useApi } from '../../src/useApi';
import { useIsDesktop } from '../../src/useResponsive';

const T = {
  primary: '#2E7D32',
  secondary: '#1976D2',
  bg: '#F5F5F5',
  card: '#FFFFFF',
  text: '#212121',
  muted: '#757575',
  ok: '#43A047',
  err: '#E53935',
  warn: '#FB8C00',
};

export default function Dashboard() {
  const { logout } = useAuth();
  const { apiFetch } = useApi();
  const isDesktop = useIsDesktop();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const [dashboard, setDashboard] = useState<any>(null);

  const [showReports, setShowReports] = useState(false);
  const [showBank, setShowBank] = useState(false);

  const [connecting, setConnecting] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);

  const fmt = (n: number = 0) =>
    `₹${Number(n || 0).toLocaleString('en-IN')}`;

  const fetchDashboard = async () => {
    try {
      const res = await apiFetch('/api/dashboard');

      if (res.ok) {
        const data = await res.json();
        setDashboard(data);
      }
    } catch (e) {
      console.log('Dashboard error:', e);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const refreshAll = () => {
    setRefreshing(true);
    fetchDashboard();
  };

  useEffect(() => {
    fetchDashboard();
  }, []);

  useFocusEffect(
    useCallback(() => {
      fetchDashboard();
    }, [])
  );

  useEffect(() => {
    const sub = ExpoLinking.addEventListener('url', ({ url }) => {
      if (
        url.includes('drive-success') ||
        url.includes('connected')
      ) {
        setTimeout(() => {
          fetchDashboard();
        }, 1200);

        Alert.alert('Success', 'Google Drive Connected');
      }
    });

    return () => sub.remove();
  }, []);

  const connectDrive = async () => {
    try {
      setConnecting(true);

      const res = await apiFetch('/api/drive/connect');

      const data = await res.json();

      if (data.authorization_url) {
        Linking.openURL(data.authorization_url);
      } else {
        Alert.alert('Error', 'Unable to connect Google Drive');
      }
    } catch {
      Alert.alert('Error', 'Unable to connect Google Drive');
    } finally {
      setConnecting(false);
    }
  };

  const disconnectDrive = async () => {
    try {
      setDisconnecting(true);

      await apiFetch('/api/drive/disconnect', {
        method: 'POST',
      });

      fetchDashboard();
    } catch {
      Alert.alert('Error', 'Disconnect failed');
    } finally {
      setDisconnecting(false);
    }
  };

  const restoreDrive = async () => {
    Alert.alert(
      'Restore Backup',
      'Restore latest backup now?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Restore',
          onPress: async () => {
            try {
              setRestoring(true);

              const res = await apiFetch(
                '/api/drive/restore',
                {
                  method: 'POST',
                }
              );

              const data = await res.json();

              Alert.alert(
                'Restore Complete',
                data.message || 'Backup restored'
              );

              setTimeout(() => {
                fetchDashboard();
              }, 1500);
            } catch {
              Alert.alert('Error', 'Restore failed');
            } finally {
              setRestoring(false);
            }
          },
        },
      ]
    );
  };

  if (loading) {
    return (
      <View style={s.center}>
        <ActivityIndicator
          size="large"
          color={T.primary}
        />
      </View>
    );
  }

  const d = dashboard || {};
  const months = d.monthly_breakdown
    ? Object.entries(d.monthly_breakdown).sort(
        (a: any, b: any) =>
          b[0].localeCompare(a[0])
      )
    : [];

  return (
    <ScrollView
      style={s.container}
      contentContainerStyle={[
        s.content,
        isDesktop && {
          maxWidth: 1200,
          alignSelf: 'center',
          width: '100%',
        },
      ]}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={refreshAll}
          colors={[T.primary]}
        />
      }
    >
      {/* Header */}
      <View style={s.header}>
        <Text style={s.headerText}>
          Aruvi Housing Solutions
        </Text>
      </View>

      {/* Main Balance */}
      <View style={[s.card, s.greenCard]}>
        <Text style={s.smallTitle}>
          Total Balance
        </Text>

        <Text style={s.mainAmount}>
          {fmt(d.total_balance)}
        </Text>

        <View style={s.rowBetween}>
          <Text style={s.whiteSmall}>
            Bank: {fmt(d.bank_balance)}
          </Text>

          <Text style={s.whiteSmall}>
            Cash: {fmt(d.petty_cash_balance)}
          </Text>
        </View>
      </View>

      {/* Stock */}
      <View
        style={[
          s.card,
          { borderLeftColor: T.secondary },
        ]}
      >
        <View style={s.rowBetween}>
          <Text style={s.cardTitle}>
            Bags in Stock
          </Text>

          <Text style={s.blueBig}>
            {d.total_stock || 0}
          </Text>
        </View>

        <View style={s.row}>
          <View style={s.stockBoxGreen}>
            <Text style={s.mutedSmall}>
              Naturoplast
            </Text>

            <Text style={s.greenBig}>
              {d.naturoplast_stock || 0}
            </Text>
          </View>

          <View style={s.stockBoxOrange}>
            <Text style={s.mutedSmall}>
              Iraniya
            </Text>

            <Text style={s.orangeBig}>
              {d.iraniya_stock || 0}
            </Text>
          </View>
        </View>
      </View>

      {/* Profit */}
      <View
        style={[
          s.card,
          {
            borderLeftColor:
              d.profit_loss >= 0
                ? T.ok
                : T.err,
          },
        ]}
      >
        <Text style={s.smallTitle}>
          Profit / Loss
        </Text>

        <Text
          style={[
            s.bigPL,
            {
              color:
                d.profit_loss >= 0
                  ? T.ok
                  : T.err,
            },
          ]}
        >
          {d.profit_loss >= 0 ? '+' : ''}
          {fmt(d.profit_loss)}
        </Text>

        <Text style={s.greenText}>
          Income: {fmt(d.total_income)}
        </Text>

        <Text style={s.redText}>
          Expense: {fmt(d.total_expenses)}
        </Text>
      </View>

      {/* Reports */}
      <TouchableOpacity
        style={s.card}
        onPress={() =>
          setShowReports(!showReports)
        }
      >
        <View style={s.rowBetween}>
          <Text style={s.cardTitle}>
            Balance Sheet & Reports
          </Text>

          <Ionicons
            name={
              showReports
                ? 'chevron-up'
                : 'chevron-down'
            }
            size={22}
            color={T.muted}
          />
        </View>
      </TouchableOpacity>

      {showReports && (
        <View style={s.card}>
          {months.length === 0 ? (
            <Text style={s.muted}>
              No reports yet
            </Text>
          ) : (
            months.map(
              ([month, vals]: any) => (
                <View
                  key={month}
                  style={s.reportBox}
                >
                  <Text style={s.bold}>
                    {month}
                  </Text>

                  <Text style={s.greenText}>
                    Income:{' '}
                    {fmt(vals.income)}
                  </Text>

                  <Text style={s.redText}>
                    Expense:{' '}
                    {fmt(vals.expense)}
                  </Text>
                </View>
              )
            )
          )}
        </View>
      )}

      {/* Bank */}
      <TouchableOpacity
        style={s.card}
        onPress={() =>
          setShowBank(!showBank)
        }
      >
        <View style={s.rowBetween}>
          <Text style={s.cardTitle}>
            Bank Account
          </Text>

          <View style={s.row}>
            <Text style={s.blueBig}>
              {fmt(d.bank_balance)}
            </Text>

            <Ionicons
              name={
                showBank
                  ? 'chevron-up'
                  : 'chevron-down'
              }
              size={22}
              color={T.muted}
            />
          </View>
        </View>
      </TouchableOpacity>

      {showBank && (
        <View style={s.card}>
          {(d.bank_transactions || [])
            .slice(0, 20)
            .map((item: any, i: number) => (
              <View
                key={i}
                style={s.bankRow}
              >
                <Text>
                  {item.description ||
                    item.type}
                </Text>

                <Text
                  style={{
                    color:
                      item.type ===
                      'Income'
                        ? T.ok
                        : T.err,
                  }}
                >
                  {item.type ===
                  'Income'
                    ? '+'
                    : '-'}
                  {fmt(item.amount)}
                </Text>
              </View>
            ))}
        </View>
      )}

      {/* Drive */}
      <View style={s.card}>
        <Text style={s.cardTitle}>
          Google Drive Backup
        </Text>

        <Text
          style={{
            marginTop: 8,
            color: d.drive_connected
              ? T.ok
              : T.err,
          }}
        >
          {d.drive_connected
            ? 'Connected'
            : 'Not connected'}
        </Text>

        {d.last_backup && (
          <Text style={s.muted}>
            Last Backup:{' '}
            {d.last_backup.folder}
          </Text>
        )}

        <View style={s.row}>
          <TouchableOpacity
            style={s.disconnectBtn}
            onPress={disconnectDrive}
          >
            {disconnecting ? (
              <ActivityIndicator
                color={T.err}
              />
            ) : (
              <Ionicons
                name="unlink"
                size={18}
                color={T.err}
              />
            )}
          </TouchableOpacity>

          <TouchableOpacity
            style={s.connectBtn}
            onPress={connectDrive}
          >
            {connecting ? (
              <ActivityIndicator
                color={T.primary}
              />
            ) : (
              <Text style={s.greenBtnTxt}>
                Connect Drive
              </Text>
            )}
          </TouchableOpacity>

          <TouchableOpacity
            style={s.restoreBtn}
            onPress={restoreDrive}
          >
            {restoring ? (
              <ActivityIndicator
                color={T.secondary}
              />
            ) : (
              <Text style={s.blueBtnTxt}>
                Restore
              </Text>
            )}
          </TouchableOpacity>
        </View>
      </View>

      {/* Logout */}
      <TouchableOpacity
        style={s.logoutBtn}
        onPress={() =>
          Alert.alert(
            'Logout',
            'Are you sure?',
            [
              {
                text: 'Cancel',
              },
              {
                text: 'Logout',
                onPress: logout,
              },
            ]
          )
        }
      >
        <Text style={s.logoutTxt}>
          Sign Out
        </Text>
      </TouchableOpacity>

      <View style={{ height: 40 }} />
    </ScrollView>
  );
}

const s = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: T.bg,
  },

  content: {
    padding: 16,
  },

  center: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },

  header: {
    backgroundColor: T.primary,
    padding: 22,
    borderRadius: 14,
    marginBottom: 16,
  },

  headerText: {
    color: '#fff',
    fontSize: 22,
    fontWeight: '700',
  },

  card: {
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 16,
    marginBottom: 14,
    borderLeftWidth: 5,
    borderLeftColor: T.primary,
    elevation: 3,
  },

  greenCard: {
    backgroundColor: T.primary,
    borderLeftWidth: 0,
  },

  smallTitle: {
    color: '#ddd',
    fontSize: 13,
  },

  mainAmount: {
    color: '#fff',
    fontSize: 34,
    fontWeight: 'bold',
    marginVertical: 10,
  },

  whiteSmall: {
    color: '#fff',
    fontSize: 13,
  },

  row: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 12,
  },

  rowBetween: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },

  cardTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: T.text,
  },

  blueBig: {
    fontSize: 26,
    fontWeight: 'bold',
    color: T.secondary,
  },

  stockBoxGreen: {
    flex: 1,
    backgroundColor: '#E8F5E9',
    padding: 12,
    borderRadius: 12,
    alignItems: 'center',
  },

  stockBoxOrange: {
    flex: 1,
    backgroundColor: '#FFF3E0',
    padding: 12,
    borderRadius: 12,
    alignItems: 'center',
  },

  mutedSmall: {
    color: T.muted,
  },

  greenBig: {
    color: T.ok,
    fontSize: 24,
    fontWeight: 'bold',
  },

  orangeBig: {
    color: T.warn,
    fontSize: 24,
    fontWeight: 'bold',
  },

  bigPL: {
    fontSize: 34,
    fontWeight: 'bold',
  },

  greenText: {
    color: T.ok,
    marginTop: 4,
  },

  redText: {
    color: T.err,
    marginTop: 4,
  },

  muted: {
    color: T.muted,
    marginTop: 8,
  },

  reportBox: {
    backgroundColor: '#F8F8F8',
    padding: 12,
    borderRadius: 12,
    marginTop: 10,
  },

  bold: {
    fontWeight: '700',
  },

  bankRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: '#eee',
  },

  disconnectBtn: {
    width: 52,
    backgroundColor: '#FFEBEE',
    justifyContent: 'center',
    alignItems: 'center',
    borderRadius: 10,
  },

  connectBtn: {
    flex: 1,
    backgroundColor: '#E8F5E9',
    padding: 14,
    borderRadius: 10,
    alignItems: 'center',
  },

  restoreBtn: {
    flex: 1,
    backgroundColor: '#E3F2FD',
    padding: 14,
    borderRadius: 10,
    alignItems: 'center',
  },

  greenBtnTxt: {
    color: T.primary,
    fontWeight: '700',
  },

  blueBtnTxt: {
    color: T.secondary,
    fontWeight: '700',
  },

  logoutBtn: {
    backgroundColor: '#FFEBEE',
    padding: 16,
    borderRadius: 12,
    alignItems: 'center',
    marginTop: 10,
  },

  logoutTxt: {
    color: T.err,
    fontWeight: '700',
    fontSize: 16,
  },
});
