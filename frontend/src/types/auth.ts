export interface LoginRequest {
  email: string
  password: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
  expires_in: number
}

export interface CurrentEmployee {
  id: string
  email: string
  display_name: string
  role: string
  team_id: string | null
}
