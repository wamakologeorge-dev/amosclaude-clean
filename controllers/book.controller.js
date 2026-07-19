'use strict';

/**
 * Amosclaud book-library controller.
 *
 * Books are a platform resource. This controller is intentionally limited to
 * HTTP validation and response handling; persistence remains in BookService
 * and autonomous decisions remain in the canonical Amosclaud kernel.
 */

const BookService = require('../services/book.service');

const RESOURCE = 'book';

function sendError(res, status, code, message) {
  return res.status(status).json({
    status: 'failed',
    error: { code, message },
    resource: RESOURCE,
  });
}

function normalizeId(value) {
  return typeof value === 'string' ? value.trim() : '';
}

function validateBookPayload(value, { partial = false } = {}) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return 'Request body must be a JSON object';
  }

  if (!partial && (!value.title || typeof value.title !== 'string')) {
    return 'title is required and must be a string';
  }

  if ('title' in value && (typeof value.title !== 'string' || !value.title.trim())) {
    return 'title must be a non-empty string';
  }

  if ('author' in value && typeof value.author !== 'string') {
    return 'author must be a string';
  }

  return null;
}

function serviceFailure(res, error, action) {
  // Do not expose database details or stack traces to platform clients.
  console.error(`[Amosclaud book-library] ${action} failed`, error);
  return sendError(res, 500, 'book_service_error', `Unable to ${action}`);
}

class BookController {
  async getAllBooks(req, res) {
    try {
      const books = await BookService.getAllBooks();
      return res.status(200).json(Array.isArray(books) ? books : []);
    } catch (error) {
      return serviceFailure(res, error, 'fetch books');
    }
  }

  async getBookById(req, res) {
    const id = normalizeId(req.params && req.params.id);
    if (!id) {
      return sendError(res, 400, 'invalid_book_id', 'A book ID is required');
    }

    try {
      const book = await BookService.getBookById(id);
      if (!book) {
        return sendError(res, 404, 'book_not_found', 'Book not found');
      }
      return res.status(200).json(book);
    } catch (error) {
      return serviceFailure(res, error, 'fetch book');
    }
  }

  async createBook(req, res) {
    const validationError = validateBookPayload(req.body);
    if (validationError) {
      return sendError(res, 400, 'invalid_book_payload', validationError);
    }

    try {
      const created = await BookService.createBook({
        ...req.body,
        title: req.body.title.trim(),
        ...(typeof req.body.author === 'string' ? { author: req.body.author.trim() } : {}),
      });
      return res.status(201).json(created);
    } catch (error) {
      return serviceFailure(res, error, 'create book');
    }
  }

  async updateBook(req, res) {
    const id = normalizeId(req.params && req.params.id);
    if (!id) {
      return sendError(res, 400, 'invalid_book_id', 'A book ID is required');
    }

    const validationError = validateBookPayload(req.body, { partial: true });
    if (validationError) {
      return sendError(res, 400, 'invalid_book_payload', validationError);
    }

    try {
      const updated = await BookService.updateBook(id, req.body);
      if (!updated) {
        return sendError(res, 404, 'book_not_found', 'Book not found');
      }
      return res.status(200).json(updated);
    } catch (error) {
      return serviceFailure(res, error, 'update book');
    }
  }

  async deleteBook(req, res) {
    const id = normalizeId(req.params && req.params.id);
    if (!id) {
      return sendError(res, 400, 'invalid_book_id', 'A book ID is required');
    }

    try {
      const deleted = await BookService.deleteBook(id);
      if (!deleted) {
        return sendError(res, 404, 'book_not_found', 'Book not found');
      }
      return res.status(204).send();
    } catch (error) {
      return serviceFailure(res, error, 'delete book');
    }
  }
}

module.exports = BookController;
module.exports.validateBookPayload = validateBookPayload;
