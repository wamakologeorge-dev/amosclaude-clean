'use strict';

/**
 * Express routes for the Amosclaud book-library resource.
 *
 * This module only maps HTTP routes to the canonical controller. It does not
 * implement a second controller, service, Agent, or Fixer.
 */

const express = require('express');
const BookController = require('../controllers/book.controller');

const router = express.Router();
const controller = new BookController();

router.get('/', controller.getAllBooks.bind(controller));
router.get('/:id', controller.getBookById.bind(controller));
router.post('/', controller.createBook.bind(controller));
router.patch('/:id', controller.updateBook.bind(controller));
router.put('/:id', controller.updateBook.bind(controller));
router.delete('/:id', controller.deleteBook.bind(controller));

module.exports = router;
