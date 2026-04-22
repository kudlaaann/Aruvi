import React, { useState, useEffect, useCallback } from "react";
import {
  View,
  Text,
  TouchableOpacity,
  Alert,
  ScrollView,
  RefreshControl,
  ActivityIndicator,
} from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as WebBrowser from "expo-web-browser";
import { FontAwesome5, MaterialIcons } from "@expo/vector-icons";

const API_URL = "https://aruvi-1-tq3k.onrender.com";

export default function Index() {
  const [driveConnected, setDriveConnected] = useState(false);
  const [loadingDrive, setLoadingDrive] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [lastBackup, setLastBackup] = useState<string | null>(null);

  // -----------------------------
  // CHECK DRIVE STATUS
  // -----------------------------
  const loadDriveStatus = async () => {
    try {
      const token = await AsyncStorage.getItem("token");

      const res = await fetch(`${API_URL}/api/drive/status`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      const data = await res.json();

      setDriveConnected(data.connected || false);
      setLastBackup(data.last_backup || null);
    } catch (error) {
      console.log("Drive status error:", error);
    }
  };

  // -----------------------------
  // CONNECT DRIVE
  // -----------------------------
  const connectDrive = async () => {
    try {
      setLoadingDrive(true);

      const token = await AsyncStorage.getItem("token");

      const authUrl = `${API_URL}/api/drive/connect?token=${token}`;

      await WebBrowser.openBrowserAsync(authUrl);

      setTimeout(() => {
        loadDriveStatus();
      }, 1500);
    } catch (error) {
      Alert.alert("Error", "Failed to connect Google Drive");
    } finally {
      setLoadingDrive(false);
    }
  };

  // -----------------------------
  // RESTORE BACKUP
  // -----------------------------
  const restoreBackup = async () => {
    Alert.alert(
      "Restore Backup",
      "Restore latest backup now?",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Restore",
          onPress: async () => {
            try {
              setRestoring(true);

              const token = await AsyncStorage.getItem("token");

              const res = await fetch(`${API_URL}/api/drive/restore`, {
                method: "POST",
                headers: {
                  Authorization: `Bearer ${token}`,
                },
              });

              const data = await res.json();

              if (res.ok) {
                Alert.alert("Restore Complete", "Restore successful");
              } else {
                Alert.alert("Error", data.detail || "Restore failed");
              }
            } catch (error) {
              Alert.alert("Error", "Restore failed");
            } finally {
              setRestoring(false);
            }
          },
        },
      ]
    );
  };

  // -----------------------------
  // REFRESH
  // -----------------------------
  const onRefresh = async () => {
    setRefreshing(true);
    await loadDriveStatus();
    setRefreshing(false);
  };

  // -----------------------------
  // SCREEN LOAD
  // -----------------------------
  useEffect(() => {
    loadDriveStatus();
  }, []);

  // -----------------------------
  // WHEN RETURN TO SCREEN
  // -----------------------------
  useFocusEffect(
    useCallback(() => {
      loadDriveStatus();
    }, [])
  );

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: "#f4f4f4" }}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
      }
    >
      {/* HEADER */}
      <View
        style={{
          backgroundColor: "#2e7d32",
          padding: 22,
          paddingTop: 55,
        }}
      >
        <Text
          style={{
            color: "white",
            fontSize: 20,
            fontWeight: "bold",
          }}
        >
          Aruvi Housing Solutions
        </Text>
      </View>

      {/* DRIVE CARD */}
      <View
        style={{
          margin: 16,
          backgroundColor: "white",
          borderRadius: 18,
          padding: 18,
          elevation: 4,
        }}
      >
        <View style={{ flexDirection: "row", alignItems: "center" }}>
          <FontAwesome5 name="cloud" size={28} color="#2e7d32" />
          <Text
            style={{
              fontSize: 24,
              fontWeight: "700",
              marginLeft: 12,
            }}
          >
            Google Drive Backup
          </Text>
        </View>

        {/* STATUS */}
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            marginTop: 18,
          }}
        >
          <MaterialIcons
            name={driveConnected ? "check-circle" : "cancel"}
            size={24}
            color={driveConnected ? "green" : "red"}
          />

          <Text
            style={{
              marginLeft: 10,
              fontSize: 18,
              color: driveConnected ? "green" : "#666",
            }}
          >
            {driveConnected ? "Connected" : "Not connected"}
          </Text>
        </View>

        {/* LAST BACKUP */}
        {lastBackup && (
          <Text
            style={{
              marginTop: 10,
              color: "#666",
              fontSize: 14,
            }}
          >
            Last Backup: {lastBackup}
          </Text>
        )}

        {/* BUTTONS */}
        <View
          style={{
            flexDirection: "row",
            marginTop: 18,
            justifyContent: "space-between",
          }}
        >
          {/* CONNECT */}
          <TouchableOpacity
            onPress={connectDrive}
            disabled={loadingDrive}
            style={{
              backgroundColor: "#dfeee0",
              flex: 1,
              padding: 14,
              borderRadius: 12,
              marginRight: 8,
              alignItems: "center",
            }}
          >
            {loadingDrive ? (
              <ActivityIndicator color="#2e7d32" />
            ) : (
              <Text
                style={{
                  color: "#2e7d32",
                  fontSize: 18,
                  fontWeight: "700",
                }}
              >
                Connect Drive
              </Text>
            )}
          </TouchableOpacity>

          {/* RESTORE */}
          <TouchableOpacity
            onPress={restoreBackup}
            disabled={restoring}
            style={{
              backgroundColor: "#dbeafe",
              flex: 1,
              padding: 14,
              borderRadius: 12,
              marginLeft: 8,
              alignItems: "center",
            }}
          >
            {restoring ? (
              <ActivityIndicator color="#2563eb" />
            ) : (
              <Text
                style={{
                  color: "#2563eb",
                  fontSize: 18,
                  fontWeight: "700",
                }}
              >
                Restore
              </Text>
            )}
          </TouchableOpacity>
        </View>

        <Text
          style={{
            marginTop: 14,
            color: "#777",
            fontSize: 14,
          }}
        >
          Auto-backup runs every 24 hours when connected
        </Text>
      </View>
    </ScrollView>
  );
}
