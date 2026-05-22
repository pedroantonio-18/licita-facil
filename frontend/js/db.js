import { openDB } from 'idb';

const DB_NAME = 'licitafacil';
const DB_VERSION = 1;
const STORE_NAME = 'recent-files';

async function getDB() {
  return openDB(DB_NAME, DB_VERSION, {
    upgrade(db) {
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, {
          keyPath: 'id',
          autoIncrement: true,
        });
        store.createIndex('createdAt', 'createdAt');
      }
    },
  });
}

export async function saveFile({ name, blob, mimeType, size, source }) {
  const db = await getDB();
  const id = await db.add(STORE_NAME, {
    name,
    blob,
    mimeType,
    size,
    source,
    createdAt: Date.now(),
  });
  return id;
}

export async function getRecentFiles(limit = 20) {
  const db = await getDB();
  const all = await db.getAllFromIndex(STORE_NAME, 'createdAt');
  return all.reverse().slice(0, limit);
}

export async function getFileById(id) {
  const db = await getDB();
  return db.get(STORE_NAME, id);
}

export async function deleteFile(id) {
  const db = await getDB();
  await db.delete(STORE_NAME, id);
}
