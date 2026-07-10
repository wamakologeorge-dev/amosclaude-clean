const mongoose = require('mongoose');

const bookSchema = new mongoose.Schema({
  title: String,
  author: String,
  publicationDate: Date
});

const Book = mongoose.model('Book', bookSchema);

module.exports = Book;
