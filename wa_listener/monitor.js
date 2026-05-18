import axios from 'axios';
import makeWASocket, {
  Browsers,
  DisconnectReason,
  USyncQuery,
  USyncUser,
  isLidUser,
  useMultiFileAuthState,
} from 'baileys';
import pino from 'pino';
import qrcode from 'qrcode-terminal';

const WEBHOOK_URL =
  process.env.WEBHOOK_URL ||
  'https://interradial-openhandedly-harmony.ngrok-free.dev/api/webhook';
const MAPPING_PENDING_URL =
  process.env.MAPPING_PENDING_URL ||
  'https://interradial-openhandedly-harmony.ngrok-free.dev/api/internal/wa-mapping/pending';
const MAPPING_UPDATE_URL =
  process.env.MAPPING_UPDATE_URL ||
  'https://interradial-openhandedly-harmony.ngrok-free.dev/api/internal/wa-mapping/update';
const AUTH_DIR = './auth';
const VERSION = [2, 3000, 1033893291];
const BASE_RECONNECT_DELAY_MS = 4000;
const MAX_RECONNECT_DELAY_MS = 30000;
const MAX_SEEN_MESSAGE_AGE_MS = 30 * 60 * 1000;
const MAX_CONTEXT_AGE_MS = 60 * 60 * 1000;
const MAPPING_SYNC_INTERVAL_MS = 45000;

let currentSocket = null;
let currentSocketId = 0;
let reconnectTimer = null;
let reconnectAttempts = 0;
let isStarting = false;
let mappingSyncTimer = null;

const lidToPnMap = new Map();
const messageContextById = new Map();
const postedMessageIds = new Map();

function normalizePhone(value) {
  if (!value) return '';

  return String(value)
    .replace(/^tel:/, '')
    .replace(/^\+/, '')
    .replace(/@s\.whatsapp\.net$/, '')
    .replace(/@c\.us$/, '')
    .replace(/[^0-9]/g, '')
    .trim();
}

function normalizePnJid(value) {
  const phone = normalizePhone(value);
  return phone ? `${phone}@s.whatsapp.net` : '';
}

function normalizeLidJid(value) {
  if (!value) return '';

  const lid = String(value).trim().replace(/^@/, '').replace(/@lid$/, '');
  return lid ? `${lid}@lid` : '';
}

function extractMessageText(message = {}) {
  return (
    message.conversation ||
    message.extendedTextMessage?.text ||
    message.imageMessage?.caption ||
    message.videoMessage?.caption ||
    ''
  ).trim();
}

function toUnixTimestamp(value) {
  if (typeof value === 'number') return value;
  if (typeof value === 'bigint') return Number(value);
  if (value && typeof value.toNumber === 'function') return value.toNumber();

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : Math.floor(Date.now() / 1000);
}

function rememberLidMapping(lidValue, pnValue, source = 'unknown') {
  const lid = normalizeLidJid(lidValue);
  const pn = normalizePnJid(pnValue);
  if (!lid || !pn) return;

  const prevPn = lidToPnMap.get(lid);
  lidToPnMap.set(lid, pn);

  if (prevPn !== pn) {
    console.log(`[LID MAP] ${lid} -> ${pn} (${source})`);
  }
}

function collectPossibleMappings(entry) {
  if (!entry) return;

  rememberLidMapping(entry.lid, entry.phoneNumber, 'contact');
  rememberLidMapping(entry.lidJid, entry.pnJid, 'chat');
  rememberLidMapping(entry.id?.endsWith('@lid') ? entry.id : '', entry.phoneNumber, 'id-phone');
  rememberLidMapping(entry.id?.endsWith('@lid') ? entry.id : '', entry.pnJid, 'id-pnJid');
  rememberLidMapping(entry.lid, entry.id?.endsWith('@s.whatsapp.net') ? entry.id : '', 'lid-id');
}

function cleanupOldEntries(map, maxAgeMs) {
  const now = Date.now();
  for (const [key, value] of map.entries()) {
    if ((value.seenAt || value.postedAt || 0) < now - maxAgeMs) {
      map.delete(key);
    }
  }
}

function rememberMessageContext(message) {
  const id = message?.key?.id;
  if (!id) return;

  messageContextById.set(id, {
    id,
    remoteJid: message?.key?.remoteJid || '',
    text: extractMessageText(message?.message),
    timestamp: toUnixTimestamp(message?.messageTimestamp),
    seenAt: Date.now(),
  });

  cleanupOldEntries(messageContextById, MAX_CONTEXT_AGE_MS);
}

function wasMessagePosted(messageId) {
  const posted = postedMessageIds.get(messageId);
  if (!posted) return false;

  if (posted.postedAt < Date.now() - MAX_SEEN_MESSAGE_AGE_MS) {
    postedMessageIds.delete(messageId);
    return false;
  }

  return true;
}

function markMessagePosted(messageId, channel) {
  postedMessageIds.set(messageId, {
    channel,
    postedAt: Date.now(),
  });
  cleanupOldEntries(postedMessageIds, MAX_SEEN_MESSAGE_AGE_MS);
}

function buildOutgoingPayload(remoteJid, messageId, text, timestamp, status = 'sent', resolved = {}) {
  return {
    event: 'messages.upsert',
    data: {
      key: {
        remoteJid,
        fromMe: true,
        id: messageId || '',
      },
      message: {
        conversation: text || '',
      },
      status,
      messageTimestamp: timestamp,
    },
    resolved,
  };
}

function resolveOutgoingJid(rawRemoteJid) {
  if (!rawRemoteJid) {
    return { resolvedJid: '', phone: '', unresolvedLid: false };
  }

  if (rawRemoteJid.endsWith('@g.us')) {
    return { resolvedJid: rawRemoteJid, phone: '', unresolvedLid: false };
  }

  if (!isLidUser(rawRemoteJid)) {
    return {
      resolvedJid: normalizePnJid(rawRemoteJid),
      phone: normalizePhone(rawRemoteJid),
      unresolvedLid: false,
    };
  }

  const lid = normalizeLidJid(rawRemoteJid);
  const mappedPn = lidToPnMap.get(lid);
  if (!mappedPn) {
    return { resolvedJid: lid, phone: '', unresolvedLid: true };
  }

  return {
    resolvedJid: mappedPn,
    phone: normalizePhone(mappedPn),
    unresolvedLid: false,
  };
}

async function postOutgoingPayload({ remoteJid, messageId, text, timestamp, status = 'sent', source }) {
  if (!remoteJid) {
    console.log('[SKIP] remoteJid kosong');
    return;
  }

  if (remoteJid.endsWith('@g.us')) {
    console.log(`[SKIP] Group chat diabaikan: ${remoteJid}`);
    return;
  }

  if (!messageId || wasMessagePosted(messageId)) {
    return;
  }

  const { resolvedJid, phone, unresolvedLid } = resolveOutgoingJid(remoteJid);
  if (unresolvedLid) {
    console.log(`[SKIP] LID belum ter-resolve: ${remoteJid}`);
    return;
  }

  const resolved = {
    phone: phone || null,
    wa_pn_jid: resolvedJid && resolvedJid.endsWith('@s.whatsapp.net') ? resolvedJid : null,
    wa_lid_jid: remoteJid && remoteJid.endsWith('@lid') ? remoteJid : null,
  };

  const payload = buildOutgoingPayload(
    remoteJid,
    messageId,
    text,
    timestamp,
    status,
    resolved
  );

  console.log(
    `[OUTGOING:${source}] ${phone || resolvedJid || remoteJid} -> ${text || '(tanpa teks)'}`
  );

  try {
    const response = await axios.post(WEBHOOK_URL, payload, {
      headers: {
        'Content-Type': 'application/json',
      },
      timeout: 15000,
    });
    markMessagePosted(messageId, source);
    console.log(`[POST SUCCESS] ${response.status} ${response.statusText}`);
  } catch (error) {
    const detail = error.response?.data || error.response?.statusText || error.message;
    console.error('[POST FAILED]', detail);
  }
}

function scheduleReconnect(reason = 'unknown') {
  if (reconnectTimer) {
    return;
  }

  reconnectAttempts += 1;
  const delay = Math.min(
    BASE_RECONNECT_DELAY_MS * Math.max(reconnectAttempts, 1),
    MAX_RECONNECT_DELAY_MS
  );

  console.log(`[RECONNECT] reason=${reason} dalam ${Math.round(delay / 1000)} detik...`);
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    startSocket().catch((error) => {
      console.error('[RECONNECT FAILED]', error);
    });
  }, delay);
}

function detachSocket(sock) {
  try {
    sock?.ev?.removeAllListeners?.();
  } catch {}
}

function stopMappingSync() {
  if (mappingSyncTimer) {
    clearInterval(mappingSyncTimer);
    mappingSyncTimer = null;
  }
}

async function resolveCustomerMapping(sock, customer) {
  const phone = normalizePhone(customer?.phone);
  if (!phone) {
    return null;
  }

  const onWhatsAppResults = await sock.onWhatsApp(phone);
  const onWhatsAppMatch = (onWhatsAppResults || []).find(
    (item) => item?.exists && normalizePhone(item.jid) === phone
  );

  if (!onWhatsAppMatch?.jid) {
    return null;
  }

  const pnJid = normalizePnJid(onWhatsAppMatch.jid);
  const query = new USyncQuery().withLIDProtocol().withContext('background');
  query.withUser(new USyncUser().withId(pnJid));

  const result = await sock.executeUSyncQuery(query);
  const row = result?.list?.find((item) => normalizePnJid(item.id) === pnJid);

  if (!row) {
    return {
      customer_id: customer.id,
      phone,
      wa_pn_jid: pnJid,
      wa_lid_jid: null,
    };
  }

  const mapping = {
    customer_id: customer.id,
    phone,
    wa_pn_jid: normalizePnJid(row.id) || pnJid,
    wa_lid_jid: row.lid || null,
  };

  if (mapping.wa_lid_jid) {
    rememberLidMapping(mapping.wa_lid_jid, mapping.wa_pn_jid, 'usync-resolve');
  }

  return mapping;
}

async function syncPendingMappings(sock) {
  try {
    const response = await axios.get(MAPPING_PENDING_URL, {
      timeout: 15000,
      params: { limit: 20 },
    });
    const customers = response.data?.customers || [];
    if (!customers.length) {
      return;
    }

    for (const customer of customers) {
      const mapping = await resolveCustomerMapping(sock, customer);
      if (!mapping || !mapping.wa_pn_jid) {
        continue;
      }

      const updateResponse = await axios.post(MAPPING_UPDATE_URL, mapping, {
        headers: {
          'Content-Type': 'application/json',
        },
        timeout: 15000,
      });

      if (updateResponse.data?.mapping_updated) {
        console.log(
          `[MAPPING SYNC] customer=${customer.phone} pn=${mapping.wa_pn_jid} lid=${mapping.wa_lid_jid || '-'}`
        );
      }
    }
  } catch (error) {
    const detail = error.response?.data || error.response?.statusText || error.message;
    console.error('[MAPPING SYNC FAILED]', detail);
  }
}

function startMappingSync(sock, socketId) {
  stopMappingSync();

  const runSync = async () => {
    if (socketId !== currentSocketId || currentSocket !== sock) {
      return;
    }
    await syncPendingMappings(sock);
  };

  runSync().catch((error) => {
    console.error('[MAPPING SYNC FAILED]', error);
  });
  mappingSyncTimer = setInterval(() => {
    runSync().catch((error) => {
      console.error('[MAPPING SYNC FAILED]', error);
    });
  }, MAPPING_SYNC_INTERVAL_MS);
}

async function handleMessagesUpsert(event) {
  const { type, messages } = event;

  for (const msg of messages || []) {
    if (!msg?.key?.fromMe) {
      continue;
    }

    rememberMessageContext(msg);

    await postOutgoingPayload({
      remoteJid: msg?.key?.remoteJid || '',
      messageId: msg?.key?.id || '',
      text: extractMessageText(msg?.message),
      timestamp: toUnixTimestamp(msg?.messageTimestamp),
      status: type === 'append' ? 'appended' : 'sent',
      source: `upsert:${type}`,
    });
  }
}

async function handleMessagesUpdate(updates) {
  for (const update of updates || []) {
    const messageId = update?.key?.id || '';
    if (!update?.key?.fromMe || !messageId || wasMessagePosted(messageId)) {
      continue;
    }

    const knownContext = messageContextById.get(messageId);
    const remoteJid = update?.key?.remoteJid || knownContext?.remoteJid || '';
    const timestamp = knownContext?.timestamp || Math.floor(Date.now() / 1000);
    const text = knownContext?.text || '';
    const statusValue = update?.update?.status;

    await postOutgoingPayload({
      remoteJid,
      messageId,
      text,
      timestamp,
      status: statusValue ? String(statusValue) : 'updated',
      source: 'messages.update',
    });
  }
}

async function startSocket() {
  if (isStarting) {
    return;
  }

  isStarting = true;
  const socketId = ++currentSocketId;

  try {
    if (currentSocket) {
      detachSocket(currentSocket);
      currentSocket = null;
    }
    stopMappingSync();

    const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
    const sock = makeWASocket({
      auth: state,
      browser: Browsers.macOS('K24 Monitor'),
      logger: pino({ level: 'silent' }),
      printQRInTerminal: false,
      version: VERSION,
      syncFullHistory: false,
    });

    currentSocket = sock;

    sock.ev.on('creds.update', saveCreds);
    sock.ev.on('lid-mapping.update', ({ lid, pn }) => {
      rememberLidMapping(lid, pn, 'lid-mapping.update');
    });
    sock.ev.on('contacts.upsert', (contacts) => {
      for (const contact of contacts || []) {
        collectPossibleMappings(contact);
      }
    });
    sock.ev.on('contacts.update', (contacts) => {
      for (const contact of contacts || []) {
        collectPossibleMappings(contact);
      }
    });
    sock.ev.on('chats.upsert', (chats) => {
      for (const chat of chats || []) {
        collectPossibleMappings(chat);
      }
    });
    sock.ev.on('chats.update', (chats) => {
      for (const chat of chats || []) {
        collectPossibleMappings(chat);
      }
    });
    sock.ev.on('messaging-history.set', ({ contacts = [], chats = [] }) => {
      for (const contact of contacts) {
        collectPossibleMappings(contact);
      }
      for (const chat of chats) {
        collectPossibleMappings(chat);
      }
    });

    sock.ev.on('connection.update', ({ connection, lastDisconnect, qr }) => {
      if (socketId !== currentSocketId) {
        return;
      }

      if (qr) {
        console.log('[QR] QR generated, silakan scan dengan WhatsApp');
        qrcode.generate(qr, { small: true });
      }

      if (connection === 'open') {
        reconnectAttempts = 0;
        if (reconnectTimer) {
          clearTimeout(reconnectTimer);
          reconnectTimer = null;
        }
        console.log('[CONNECTED] WhatsApp listener tersambung');
        startMappingSync(sock, socketId);
      }

      if (connection === 'close') {
        const statusCode = lastDisconnect?.error?.output?.statusCode;
        const loggedOut = statusCode === DisconnectReason.loggedOut;
        const reason = statusCode ?? 'unknown';

        console.log(`[DISCONNECTED] statusCode=${reason} reconnect=${!loggedOut}`);

        if (loggedOut) {
          console.log('[LOGGED OUT] Session terputus permanen, hapus folder auth lalu scan ulang.');
          return;
        }

        currentSocket = null;
        stopMappingSync();
        if (statusCode === DisconnectReason.connectionReplaced) {
          scheduleReconnect('connectionReplaced');
          return;
        }

        if (statusCode === DisconnectReason.restartRequired) {
          scheduleReconnect('restartRequired');
          return;
        }

        scheduleReconnect(String(reason));
      }
    });

    sock.ev.on('messages.upsert', async (event) => {
      if (socketId !== currentSocketId) {
        return;
      }

      await handleMessagesUpsert(event);
    });

    sock.ev.on('messages.update', async (updates) => {
      if (socketId !== currentSocketId) {
        return;
      }

      await handleMessagesUpdate(updates);
    });
  } finally {
    isStarting = false;
  }
}

startSocket().catch((error) => {
  console.error('[FATAL]', error);
  process.exit(1);
});
