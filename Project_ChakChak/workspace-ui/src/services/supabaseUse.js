import { createClient } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

function disabledSupabase() {
  const ok = { data: null, error: null }
  const chain = {
    insert: async () => ok,
    select: async () => ok,
    update: async () => ok,
    delete: async () => ok,
    upsert: async () => ok,
    eq: () => chain,
    order: () => chain,
    limit: () => chain,
    single: async () => ok,
  }
  return {
    from: () => chain,
    storage: {
      from: () => ({
        upload: async () => ok,
        getPublicUrl: () => ({ data: { publicUrl: '' } }),
      }),
    },
  }
}

export const isSupabaseEnabled = Boolean(supabaseUrl && supabaseAnonKey)

export const supabase = isSupabaseEnabled
  ? createClient(supabaseUrl, supabaseAnonKey)
  : disabledSupabase()
