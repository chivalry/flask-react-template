import { zodResolver } from '@hookform/resolvers/zod'
import { Alert, Box, Button, Container, TextField, Typography } from '@mui/material'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate } from 'react-router-dom'
import { z } from 'zod'

import { login, me, register as registerUser } from '../api/auth'
import { useAuthStore } from '../store/auth'

const schema = z
  .object({
    email: z.string().email('Enter a valid email.'),
    password: z.string().min(8, 'Password must be at least 8 characters.'),
    confirmPassword: z.string(),
  })
  .refine((d) => d.password === d.confirmPassword, {
    message: 'Passwords do not match.',
    path: ['confirmPassword'],
  })

type FormData = z.infer<typeof schema>

export default function Register() {
  const navigate = useNavigate()
  const setUser = useAuthStore((s) => s.setUser)
  const [apiError, setApiError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({ resolver: zodResolver(schema) })

  const onSubmit = async (data: FormData) => {
    setApiError(null)
    try {
      await registerUser(data.email, data.password)
      await login(data.email, data.password)
      const { data: user } = await me()
      setUser(user)
      navigate('/')
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { error?: string } } })?.response?.data?.error ??
        'Registration failed.'
      setApiError(msg)
    }
  }

  return (
    <Container maxWidth="xs" sx={{ mt: 8 }}>
      <Typography variant="h5" gutterBottom>
        Create account
      </Typography>
      {apiError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {apiError}
        </Alert>
      )}
      <Box component="form" onSubmit={handleSubmit(onSubmit)} noValidate>
        <TextField
          {...register('email')}
          label="Email"
          type="email"
          fullWidth
          margin="normal"
          error={!!errors.email}
          helperText={errors.email?.message}
        />
        <TextField
          {...register('password')}
          label="Password"
          type="password"
          fullWidth
          margin="normal"
          error={!!errors.password}
          helperText={errors.password?.message}
        />
        <TextField
          {...register('confirmPassword')}
          label="Confirm password"
          type="password"
          fullWidth
          margin="normal"
          error={!!errors.confirmPassword}
          helperText={errors.confirmPassword?.message}
        />
        <Button
          type="submit"
          variant="contained"
          fullWidth
          sx={{ mt: 2 }}
          disabled={isSubmitting}
        >
          {isSubmitting ? 'Creating account…' : 'Create account'}
        </Button>
        <Typography variant="body2" sx={{ mt: 2 }}>
          Already have an account? <Link to="/login">Sign in</Link>
        </Typography>
      </Box>
    </Container>
  )
}
