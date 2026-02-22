package com.mathgrader.service;

import com.mathgrader.model.User;
import com.mathgrader.model.UserDTO;
import com.mathgrader.repository.UserRepository;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class UserService {

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;

    public UserService(UserRepository userRepository, PasswordEncoder passwordEncoder) {
        this.userRepository = userRepository;
        this.passwordEncoder = passwordEncoder;
    }

    public Page<UserDTO> findAll(Pageable pageable) {
        return userRepository.findAll(pageable).map(this::toDTO);
    }

    @Transactional
    public UserDTO create(UserDTO dto) {
        if (userRepository.findByUsername(dto.getUsername()).isPresent()) {
            throw new IllegalArgumentException("Username already exists");
        }
        User user = new User();
        user.setUsername(dto.getUsername());
        user.setPassword(passwordEncoder.encode(dto.getPassword()));
        user.setRole(dto.getRole() != null ? dto.getRole() : "ROLE_STUDENT");
        return toDTO(userRepository.save(user));
    }

    @Transactional
    public UserDTO update(Long id, UserDTO dto) {
        User user = userRepository.findById(id)
                .orElseThrow(() -> new IllegalArgumentException("User not found"));
        
        // Update fields if provided
        if (dto.getUsername() != null && !dto.getUsername().isEmpty() && !user.getUsername().equals(dto.getUsername())) {
             if (userRepository.findByUsername(dto.getUsername()).isPresent()) {
                throw new IllegalArgumentException("Username already exists");
            }
            user.setUsername(dto.getUsername());
        }
        
        if (dto.getPassword() != null && !dto.getPassword().isEmpty()) {
            user.setPassword(passwordEncoder.encode(dto.getPassword()));
        }
        
        if (dto.getRole() != null && !dto.getRole().isEmpty()) {
            user.setRole(dto.getRole());
        }
        
        return toDTO(userRepository.save(user));
    }

    @Transactional
    public void delete(Long id) {
        userRepository.deleteById(id);
    }

    private UserDTO toDTO(User user) {
        UserDTO dto = new UserDTO();
        dto.setId(user.getId());
        dto.setUsername(user.getUsername());
        dto.setRole(user.getRole());
        // Don't return password
        return dto;
    }
}
