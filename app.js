// app.js

const express = require('express');
const BookController = require('./controllers/book.controller');

const app = express();
app.use(express.json());

const bookController = new BookController();

app.get('/books', bookController.getAllBooks);
app.get('/books/:id', bookController.getBookById);
app.post('/books', bookController.createBook);
app.put('/books/:id', bookController.updateBook);
app.delete('/books/:id', bookController.deleteBook);

app.listen(3000, () => {
  console.log('Server listening on port 3000');
});
