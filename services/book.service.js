// services/book.service.js

const BookModel = require('../models/book.model');

class BookService {
  async getAllBooks() {
    return await BookModel.find();
  }

  async getBookById(id) {
    return await BookModel.findById(id);
  }

  async createBook(book) {
    return await BookModel.create(book);
  }

  async updateBook(id, book) {
    return await BookModel.findByIdAndUpdate(id, book, { new: true });
  }

  async deleteBook(id) {
    return await BookModel.findByIdAndDelete(id);
  }
}

module.exports = new BookService();
