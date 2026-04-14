export interface PaginatedResponse<T> {
  items: T[];
  nextCursor?: string;
  count: number;
}

export interface ApiError {
  statusCode: number;
  message: string;
  error?: string;
}
