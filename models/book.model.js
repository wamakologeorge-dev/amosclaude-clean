'use strict';

/**
 * Lightweight repository-backed book model.
 *
 * This fills the missing persistence dependency used by BookService without
 * creating another database service. The storage path can be redirected to a
 * persistent Amosclaud volume with AMOSCLAUD_BOOK_STORE.
 */

const crypto = require('crypto');
const fs = require('fs/promises');
const path = require('path');

const STORE_PATH = path.resolve(
  process.env.AMOSCLAUD_BOOK_STORE || path.join(process.cwd(), 'data', 'books.json'),
);

let writeQueue = Promise.resolve();

async function readAll() {
  try {
    const raw = await fs.readFile(STORE_PATH, 'utf8');
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    if (error.code === 'ENOENT') return [];
    throw error;
  }
}

async function persist(books) {
  await fs.mkdir(path.dirname(STORE_PATH), { recursive: true });
  const temporary = `${STORE_PATH}.${process.pid}.tmp`;
  await fs.writeFile(temporary, `${JSON.stringify(books, null, 2)}\n`, 'utf8');
  await fs.rename(temporary, STORE_PATH);
}

function serialize(operation) {
  const current = writeQueue.then(operation, operation);
  writeQueue = current.catch(() => undefined);
  return current;
}

class BookModel {
  static async find() {
    return readAll();
  }

  static async findById(id) {
    const books = await readAll();
    return books.find((book) => String(book.id) === String(id)) || null;
  }

  static async create(payload) {
    return serialize(async () => {
      const books = await readAll();
      const now = new Date().toISOString();
      const book = {
        ...payload,
        id: crypto.randomUUID(),
        createdAt: now,
        updatedAt: now,
      };
      books.push(book);
      await persist(books);
      return book;
    });
  }

  static async findByIdAndUpdate(id, payload) {
    return serialize(async () => {
      const books = await readAll();
      const index = books.findIndex((book) => String(book.id) === String(id));
      if (index < 0) return null;

      const updated = {
        ...books[index],
        ...payload,
        id: books[index].id,
        createdAt: books[index].createdAt,
        updatedAt: new Date().toISOString(),
      };
      books[index] = updated;
      await persist(books);
      return updated;
    });
  }

  static async findByIdAndDelete(id) {
    return serialize(async () => {
      const books = await readAll();
      const index = books.findIndex((book) => String(book.id) === String(id));
      if (index < 0) return null;
      const [deleted] = books.splice(index, 1);
      await persist(books);
      return deleted;
    });
  }
}

module.exports = BookModel;
module.exports.STORE_PATH = STORE_PATH;
