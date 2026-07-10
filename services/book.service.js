const Book = require('../models/book.model');

class BookService {
  async getAllBooks() {
    return await Book.find();
  }

  async getBookById(id) {
    return await Book.findById(id);
  }

  async createBook(book) {
    return await Book.create(book);
  }

  async updateBook(id, book) {
    return await Book.findByIdAndUpdate(id, book, { new: true });
  }

  async deleteBook(id) {
    return await Book.findByIdAndRemove(id);
  }
}

module.exports = BookService;
