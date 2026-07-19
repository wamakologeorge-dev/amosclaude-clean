const BookService = require('../services/book.service');

class BookController {
  async getAllBooks(req, res) {
    const books = await BookService.getAllBooks();
    res.json(books);
  }

  async getBookById(req, res) {
    const id = req.params.id;
    const book = await BookService.getBookById(id);
    res.json(book);
  }

  async createBook(req, res) {
    const book = req.body;
    const newBook = await BookService.createBook(book);
    res.json(newBook);
  }

  async updateBook(req, res) {
    const id = req.params.id;
    const book = req.body;
    const updatedBook = await BookService.updateBook(id, book);
    res.json(updatedBook);
  }

  async deleteBook(req, res) {
    const id = req.params.id;
    await BookService.deleteBook(id);
    res.json({ message: 'Book deleted successfully' });
  }
}

module.exports = BookController;
