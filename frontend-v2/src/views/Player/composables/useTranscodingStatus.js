import { ref, computed, watch } from "vue";
import { systemApi } from "@/api/system";
import { playerApi } from "@/api/player";
import { buildAuthedWsUrl } from "@/utils/wsAuth";

export function useTranscodingStatus({
  currentQuality,
  isAudio,
  isImage,
  isGallery,
  originalVideoInfo
}) {
  const gpuStatusData = ref({ summary: { has_gpu: false }, gpus: [] });
  const gpuStatusLoading = ref(true);
  const gpuStatusError = ref("");
  const encoderLabel = ref("");
  const transcodeStatus = ref({});
  const stableSideInfoLabel = ref("");
  let gpuRefreshInterval = null;
  let encoderSocket = null;
  let encoderSocketTimer = null;

  const showTranscodeInfo = computed(() => {
    return (
      !!encoderLabel.value &&
      currentQuality.value !== "original" &&
      !isAudio.value &&
      !isImage.value
    );
  });

  const gpuPrimaryVendorLabel = computed(() => {
    const gpuList = Array.isArray(gpuStatusData.value?.gpus)
      ? gpuStatusData.value.gpus
      : [];
    const normalizeVendor = (value) => {
      const text = String(value || "")
        .trim()
        .toLowerCase();
      if (!text) return "";
      if (text.includes("intel")) return "intel";
      if (text.includes("nvidia")) return "nvidia";
      if (text.includes("amd")) return "amd";
      return text;
    };
    const parseGpuIndex = (value) => {
      if (value === undefined || value === null || value === "") return null;
      const parsed = Number.parseInt(String(value).trim(), 10);
      return Number.isFinite(parsed) ? parsed : null;
    };
    const pickPreferred = (list) => {
      if (!Array.isArray(list) || list.length === 0) return null;
      const ok = list.find(
        (gpu) => String(gpu?.status || "").toLowerCase() === "ok"
      );
      if (ok) return ok;
      const degradedUsable = list.find((gpu) => {
        const status = String(gpu?.status || "").toLowerCase();
        return status === "degraded" && Boolean(gpu?.transcode_enabled);
      });
      if (degradedUsable) return degradedUsable;
      const nonError = list.find(
        (gpu) => String(gpu?.status || "").toLowerCase() !== "error"
      );
      return nonError || list[0] || null;
    };
    const summary = gpuStatusData.value?.summary || {};
    const activeTranscoder = summary.active_transcoder || {};
    const activeVendor = normalizeVendor(
      summary.active_vendor || activeTranscoder.vendor
    );
    const activeHwaccel = String(
      summary.active_hwaccel || activeTranscoder.hardware || ""
    )
      .trim()
      .toLowerCase();
    const activeGpuIndex = parseGpuIndex(
      summary.active_gpu_index ?? activeTranscoder.gpu_index
    );
    const explicitActive = gpuList.find((gpu) => Boolean(gpu?.is_active));
    let primaryGpu = explicitActive || null;
    if (!primaryGpu && activeVendor) {
      const sameVendor = gpuList.filter(
        (gpu) => normalizeVendor(gpu?.vendor) === activeVendor
      );
      if (sameVendor.length > 0) {
        if (activeVendor === "nvidia" && activeGpuIndex !== null) {
          primaryGpu =
            sameVendor.find(
              (gpu) => parseGpuIndex(gpu?.index) === activeGpuIndex
            ) || null;
        }
        if (!primaryGpu) primaryGpu = pickPreferred(sameVendor);
      }
    }
    if (!primaryGpu && activeHwaccel === "vaapi") {
      const vaapiCapable = gpuList.filter((gpu) => {
        const backends = Array.isArray(gpu?.transcode_backends)
          ? gpu.transcode_backends
          : [];
        return backends
          .map((item) => String(item || "").toLowerCase())
          .includes("vaapi");
      });
      if (vaapiCapable.length > 0) primaryGpu = pickPreferred(vaapiCapable);
    }
    if (!primaryGpu) primaryGpu = pickPreferred(gpuList);
    const rawVendor = String(primaryGpu?.vendor || "")
      .toLowerCase()
      .trim();
    if (!rawVendor) return "";
    if (rawVendor.includes("intel")) return "Intel";
    if (rawVendor.includes("nvidia")) return "NVIDIA";
    if (rawVendor.includes("amd")) return "AMD";
    return rawVendor.toUpperCase();
  });

  const transcodeHardwareLabel = computed(() => {
    const text = String(encoderLabel.value || "").toLowerCase();
    if (!text) return "";
    if (text.includes("nvenc") || text.includes("cuda")) return "NVIDIA";
    if (text.includes("qsv")) return "Intel";
    if (text.includes("amf")) return "AMD";
    if (text.includes("vaapi")) return gpuPrimaryVendorLabel.value || "GPU";
    if (text.includes("libx") || text.includes("svt") || text.includes("cpu"))
      return "CPU";
    return gpuPrimaryVendorLabel.value || "";
  });

  const transcodeFrameInterpolationLabel = computed(() => {
    const payload = transcodeStatus.value || {};
    const active = Boolean(payload.frame_interpolation_active);
    if (!active) return "插帧×";
    const mode = String(payload.frame_interpolation_mode || "").toLowerCase();
    if (mode === "30to60") return "插帧30→60√";
    if (mode === "60to120") return "插帧60→120√";
    const target = Number(payload.frame_interpolation_target_fps);
    if (Number.isFinite(target) && target > 0)
      return `插帧→${Math.round(target)}√`;
    return "插帧√";
  });

  const formatBitrateLabel = (bitrate) => {
    const bps = Number(bitrate);
    if (!isFinite(bps) || bps <= 0) return "";
    if (bps >= 1000000) return `${(bps / 1000000).toFixed(2)}Mbps`;
    if (bps >= 1000) return `${(bps / 1000).toFixed(0)}Kbps`;
    return `${Math.round(bps)}bps`;
  };

  const showOriginalVideoInfo = computed(() => {
    return (
      !isAudio.value &&
      !isImage.value &&
      !isGallery.value &&
      currentQuality.value === "original"
    );
  });

  const originalInfoLabel = computed(() => {
    if (!showOriginalVideoInfo.value) return "";
    const info = originalVideoInfo.value || {};
    const parts = [];
    if (info.width && info.height) {
      parts.push(`${info.width}x${info.height}`);
    }
    const bitrate = info.videoBitrate || info.formatBitrate;
    const bitrateLabel = formatBitrateLabel(bitrate);
    if (bitrateLabel) {
      parts.push(bitrateLabel);
    }
    if (parts.length === 0) return "";
    return `原始: ${parts.join(" · ")}`;
  });

  const sideInfoLabel = computed(() => {
    if (showTranscodeInfo.value) {
      const hw = transcodeHardwareLabel.value;
      const base = hw
        ? `转码(${hw}): ${encoderLabel.value}`
        : `转码: ${encoderLabel.value}`;
      return `${base} · ${transcodeFrameInterpolationLabel.value}`;
    }
    return originalInfoLabel.value;
  });


  watch(sideInfoLabel, (value) => {
    if (value) {
      stableSideInfoLabel.value = value;
    }
  });

  const displaySideInfoLabel = computed(
    () => sideInfoLabel.value || stableSideInfoLabel.value
  );

  const refreshQualitySuffix = async () => {
    try {
      const res = await playerApi.getEncoderStatus();
      encoderLabel.value = res.label || "";
      transcodeStatus.value = res || {};
    } catch (error) {
      encoderLabel.value = "";
      transcodeStatus.value = {};
    }
  };

  const refreshGpuStatus = async () => {
    try {
      const data = await systemApi.getGpuStats();
      gpuStatusData.value = data || { summary: { has_gpu: false }, gpus: [] };
      gpuStatusError.value = "";
    } catch (error) {
      gpuStatusError.value = error?.message || "gpu_status_failed";
    } finally {
      gpuStatusLoading.value = false;
    }
  };

  const startGpuStatusPolling = () => {
    if (gpuRefreshInterval) clearInterval(gpuRefreshInterval);
    refreshGpuStatus();
    gpuRefreshInterval = setInterval(refreshGpuStatus, 1000);
  };

  const stopGpuStatusPolling = () => {
    if (gpuRefreshInterval) {
      clearInterval(gpuRefreshInterval);
      gpuRefreshInterval = null;
    }
  };

  const setupEncoderSocket = () => {
    if (encoderSocket) {
      try {
        encoderSocket.close();
      } catch (e) {}
      encoderSocket = null;
    }

    const url = buildAuthedWsUrl("/api/ws/subscribe/transcode");

    try {
      const ws = new WebSocket(url);
      encoderSocket = ws;

      ws.onopen = () => {
        if (encoderSocketTimer) clearInterval(encoderSocketTimer);
        encoderSocketTimer = setInterval(() => {
          try {
            ws.send("ping");
          } catch (e) {}
        }, 15000);
      };

      ws.onmessage = (event) => {
        try {
          if (event.data === "pong") return;
          const message = JSON.parse(event.data);
          if (message && message.type === "transcode_update" && message.payload) {
            encoderLabel.value = message.payload.label || "";
            transcodeStatus.value = message.payload || {};
          }
        } catch (e) {
          console.warn("Parse transcode msg failed", e);
        }
      };

      const cleanup = () => {
        if (encoderSocketTimer) {
          clearInterval(encoderSocketTimer);
          encoderSocketTimer = null;
        }
        encoderSocket = null;
        // 重连机制
        setTimeout(setupEncoderSocket, 5000);
      };

      ws.onerror = cleanup;
      ws.onclose = cleanup;
    } catch (e) {
      console.error("Setup encoder socket failed", e);
      setTimeout(setupEncoderSocket, 5000);
    }
  };
  
  const cleanupEncoderSocket = () => {
    if (encoderSocket) {
      try {
        encoderSocket.close();
      } catch (e) {}
      encoderSocket = null;
    }
    if (encoderSocketTimer) {
      clearInterval(encoderSocketTimer);
      encoderSocketTimer = null;
    }
  };

  return {
    gpuStatusData,
    gpuStatusLoading,
    gpuStatusError,
    encoderLabel,
    transcodeStatus,
    stableSideInfoLabel,
    showTranscodeInfo,
    displaySideInfoLabel,
    refreshQualitySuffix,
    startGpuStatusPolling,
    stopGpuStatusPolling,
    setupEncoderSocket,
    cleanupEncoderSocket
  };
}
