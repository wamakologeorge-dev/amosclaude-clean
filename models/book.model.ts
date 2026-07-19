// amosclaude-clean/models/book.model.ts

interface Book {
  id: string;
  title: string;
  author: string;
  publicationDate: Date;
  isbn: string;
  description: string;
}

class BookModel {
  private books: Book[] = [];

  public addBook(book: Book): void {
    this.books.push(book);
  }

  public getBooks(): Book[] {
    return this.books;
  }

  public getBookById(id: string): Book | undefined {
    return this.books.find((book) => book.id === id);
  }

  public updateBook(id: string, updatedBook: Book): void {
    const index = this.books.findIndex((book) => book.id === id);
    if (index !== -1) {
      this.books[index] = updatedBook;
    }
  }

  public deleteBook(id: string): void {
    this.books = this.books.filter((book) => book.id !== id);
  }
}

export default BookModel;
