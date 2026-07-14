// services/book.service.ts
import { Injectable } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { Book } from './book.entity';

@Injectable()
export class BookService {
  constructor(
    @InjectRepository(Book)
    private readonly bookRepository: Repository<Book>,
  ) {}

  async getBook(id: number): Promise<Book> {
    return this.bookRepository.findOneBy({ id });
  }

  async createBook(book: Book): Promise<Book> {
    return this.bookRepository.save(book);
  }

  async updateBook(id: number, book: Book): Promise<Book> {
    await this.bookRepository.update(id, book);
    return this.getBook(id);
  }

  async deleteBook(id: number): Promise<void> {
    await this.bookRepository.delete(id);
  }
}
