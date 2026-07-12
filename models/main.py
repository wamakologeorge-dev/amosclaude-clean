"""Minimal in-memory book API example."""

from pydantic import BaseModel
from fastapi import FastAPI


class Book(BaseModel):
    id: str
    title: str
    author: str


class BookModel:
    def __init__(self) -> None:
        self._books: list[Book] = []

    def add_book(self, book: Book) -> None:
        self._books.append(book)


app = FastAPI()
book_model = BookModel()


@app.post("/books/")
async def create_book(book: Book) -> Book:
    book_model.add_book(book)
    return book
