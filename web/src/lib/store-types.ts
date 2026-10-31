export interface StoreStats {
  product_count: number;
  order_count: number;
  item_sales_amount: number;
  avg_rating: number;
  sales_definition: string;
}

export interface StoreOrder {
  id: string;
  status: string;
  total: number;
  date: string;
  buyer_name: string;
  buyer_email: string;
  item_count: number;
}

export interface StoreProduct {
  id: string;
  name: string;
  description: string;
  category: string;
  brand: string | null;
  price: number;
  original_price: number | null;
  image_url: string | null;
  rating: number;
  review_count: number;
  is_active: boolean;
}
