/** @file The MUI theme shared by the whole application. */

import { createTheme } from '@mui/material'

const { breakpoints } = createTheme()

/** The application theme: MUI's defaults in light mode, inputs 16px below `sm`. */
export const theme = createTheme({
    palette: { mode: 'light' },
    components: {
        MuiInputBase: {
            styleOverrides: {
                // iOS Safari zooms the page when a focused input's text is under 16px.
                input: { [breakpoints.down('sm')]: { fontSize: 16 } },
            },
        },
    },
})
