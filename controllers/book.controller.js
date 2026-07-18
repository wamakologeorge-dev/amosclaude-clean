// controllers/book.controller.js

/**
 * Book Controller
 * @description Handles book-related operations
 */

const BookService = require('../services/book.service');

/**
 * Book Controller Class
 */
class BookController {
  /**
   * Get all books
   * @param {Object} req - Express request object
   * @param {Object} res - Express response object
   * @returns {Promise<void>}
   */
  async getAllBooks(req, res) {
    try {
      const books = await BookService.getAllBooks();
      res.json(books);
    } catch (error) {
      res.status(500).json({ message: 'Error fetching books' });
    }
  }

  /**
   * Get a book by ID
   * @param {Object} req - Express request object
   * @param {Object} res - Express response object
   * @returns {Promise<void>}
   */
  async getBookById(req, res) {
    try {
      const id = req.params.id;
      const book = await BookService.getBookById(id);
      if (!book) {
        res.status(404).json({ message: 'Book not found' });
      } else {
        res.json(book);
      }
    } catch (error) {
      res.status(500).json({ message: 'Error fetching book' });
    }
  }

  /**
   * Create a new book
   * @param {Object} req - Express request object
   * @param {Object} res - Express response object
   * @returns {Promise<void>}
   */
  async createBook(req, res) {
    try {
      const book = req.body;
      const newBook = await BookService.createBook(book);
      res.json(newBook);
    } catch (error) {
      res.status(500).json({ message: 'Error creating book' });
    }
  }

  /**
   * Update a book
   * @param {Object} req - Express request object
   * @param {Object} res - Express response object
   * @returns {Promise<void>}
   */
  async updateBook(req, res) {
    try {
      const id = req.params.id;
      const book = req.body;
      const updatedBook = await BookService.updateBook(id, book);
      if (!updatedBook) {
        res.status(404).json({ message: 'Book not found' });
      } else {
        res.json(updatedBook);
      }
    } catch (error) {
      res.status(500).json({ message: 'Error updating book' });
    }
  }

  /**
   * Delete a book
   * @param {Object} req - Express request object
   * @param {Object} res - Express response object
   * @returns {Promise<void>}
   */
  async deleteBook(req, res) {
    try {
      const id = req.params.id;
      await BookService.deleteBook(id);
      res.json({ message: 'Book deleted successfully' });
    } catch (error) {
      res.status(500).json({ message: 'Error deleting book' });
    }
  }
}

module.exports = BookController;
