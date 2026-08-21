export type Status = 'WAITING' | 'AWAITING_CALL' | 'ACTIVE' | 'COMPLETED'
export interface Me {
    telegram_id: number
    first_name?: string
    username?: string
    is_admin: boolean
    rating: string
    photo_url: string
}
export interface Job {
    id: number;
    public_text: string;
    full_text?: string;
    status: Status;
    created_at: string;
    closed_at?: string;
    final_amount?: number;
    assignee_name?: string
    comment_text?: string
    comment_created_at?: string
    comment_updated_at?: string
}
export interface User {
    telegram_id: number
    first_name?: string
    username?: string
    is_admin: boolean
    is_active: boolean
    rating: string
    active_jobs: number
    completed_jobs: number
}
