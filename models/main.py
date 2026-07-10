# main.py
from fastapi import FastAPI
from .models.book.model import BookModel

app = FastAPI()

book_model = BookModel()

@app.post("/books/")
async def create_book(book: Book):
    book_model.addBook(book)
    return book
